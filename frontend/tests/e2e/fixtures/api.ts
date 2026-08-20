/** Direct API reads for spec setup that has no UI dependency. */
import type { Page } from '@playwright/test'
import { z } from 'zod'

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export async function getCompanyDefaults(page: Page): Promise<Record<string, unknown>> {
  const response = await page.request.get('/api/company-defaults/', {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok()) {
    throw new Error(`Company defaults read failed: ${response.status()} ${await response.text()}`)
  }
  const payload: unknown = await response.json()
  if (!isRecord(payload)) {
    throw new Error(`Company defaults response was not an object: ${JSON.stringify(payload)}`)
  }
  return payload
}

const jobLabourRateSchema = z.object({
  id: z.string(),
  labour_subtype: z.string(),
  labour_subtype_name: z.string(),
  charge_out_rate: z.string(),
  is_workshop: z.boolean(),
})
export type JobLabourRate = z.infer<typeof jobLabourRateSchema>

export async function getJobLabourRates(page: Page, jobId: string): Promise<JobLabourRate[]> {
  const response = await page.request.get(`/api/job/jobs/${jobId}/labour-rates/`)
  if (!response.ok()) {
    throw new Error(`Job labour rates read failed: ${response.status()} ${await response.text()}`)
  }
  return z.array(jobLabourRateSchema).parse(await response.json())
}

const authenticatedProfileSchema = z.object({
  id: z.string(),
  office_email: z.string(),
  is_office_staff: z.boolean(),
  is_superuser: z.boolean(),
})
export type AuthenticatedProfile = z.infer<typeof authenticatedProfileSchema>

/** The authenticated E2E user's profile — the one staff row every spec can rely on. */
export async function getMe(page: Page): Promise<AuthenticatedProfile> {
  const response = await page.request.get('/api/accounts/me/')
  if (!response.ok()) {
    throw new Error(`Profile read failed: ${response.status()} ${await response.text()}`)
  }
  return authenticatedProfileSchema.parse(await response.json())
}

// ── Timesheet reference data (entry-cluster specs) ───────────────────────

const timesheetStaffSchema = z.object({
  id: z.string(),
  name: z.string(),
  wageRate: z.string(),
})
export type TimesheetStaff = z.infer<typeof timesheetStaffSchema>

/** Staff selectable for time entry on a date (superuser management surface). */
export async function getTimesheetStaff(page: Page, date: string): Promise<TimesheetStaff[]> {
  const response = await page.request.get(`/api/timesheets/staff/?date=${date}`)
  if (!response.ok()) {
    throw new Error(`Timesheet staff read failed: ${response.status()} ${await response.text()}`)
  }
  return z.object({ staff: z.array(timesheetStaffSchema) }).parse(await response.json()).staff
}

const timesheetJobSchema = z.object({
  id: z.string(),
  job_number: z.number(),
  name: z.string(),
  is_urgent: z.boolean(),
  labour_rates: z.array(jobLabourRateSchema),
})
export type TimesheetJob = z.infer<typeof timesheetJobSchema>

/** Jobs available in the timesheet job picker. */
export async function getTimesheetJobs(page: Page): Promise<TimesheetJob[]> {
  const response = await page.request.get('/api/timesheets/jobs/')
  if (!response.ok()) {
    throw new Error(`Timesheet jobs read failed: ${response.status()} ${await response.text()}`)
  }
  return z.object({ jobs: z.array(timesheetJobSchema) }).parse(await response.json()).jobs
}

const staffListItemSchema = z.object({
  id: z.string(),
  office_email: z.string(),
  wage_rate: z.string(),
  base_wage_rate: z.string(),
  date_left: z.string().nullable(),
})
export type StaffListItem = z.infer<typeof staffListItemSchema>

/** The staff admin list (all staff, departed included; superuser only). */
export async function getStaffList(page: Page): Promise<StaffListItem[]> {
  const response = await page.request.get('/api/accounts/staff/')
  if (!response.ok()) {
    throw new Error(`Staff list read failed: ${response.status()} ${await response.text()}`)
  }
  return z.array(staffListItemSchema).parse(await response.json())
}

const payRunListSchema = z.object({
  next_postable_week_start_date: z.string().nullable(),
})

/**
 * The one week Xero will currently accept a pay run for, as the server rules it.
 *
 * Opus: Read, never computed. Xero processes pay runs in sequence and creates the
 * calendar's next unprocessed period regardless of what is requested, so a
 * guessed week is simply wrong — a restored demo tenant has no pay runs at all
 * and answers with the calendar's anchor, four weeks back.
 */
/**
 * Bring the pay-run mirror current, through the product's own door.
 *
 * Fable: Posting refreshes the mirror BEFORE judging the week, and refuses an
 * out-of-order week after that refresh — with no run started and the claim
 * released — so a deliberately unpostable week is exactly a mirror refresh.
 * The harness needs one because teardown restores the database out from under
 * Xero, and the postable-week answer is computed from the mirror. There is no
 * standalone refresh endpoint to reach for: refreshing is a step of posting,
 * not an operator intent, and the UI's banner is advisory for the same reason.
 * 2001-01-01 is a Monday — it must pass the Monday check, or the refusal would
 * fire BEFORE the refresh — and can never post: any calendar with runs names a
 * later postable week, and an empty one has no staff employed in 2001.
 */
export async function refreshPayrollMirror(page: Page): Promise<void> {
  const response = await page.request.post('/api/timesheets/payroll/post-staff-week/', {
    data: { week_start_date: '2001-01-01' },
  })
  if (response.status() !== 400) {
    throw new Error(
      `The mirror-refreshing probe expected a 400 refusal, got ${response.status()}: ` +
        (await response.text()),
    )
  }
}

export async function getPostableWeek(page: Page): Promise<string> {
  const response = await page.request.get('/api/timesheets/payroll/pay-runs/')
  if (!response.ok()) {
    throw new Error(`Pay run read failed: ${response.status()} ${await response.text()}`)
  }
  const { next_postable_week_start_date: week } = payRunListSchema.parse(await response.json())
  if (week === null) {
    throw new Error(
      'The server reports no postable week for the payroll calendar. Run ' +
        '`python manage.py xero --setup --seed-xero` and check the calendar exists.',
    )
  }
  return week
}

const staffWeekPostingSchema = z.object({
  staff_id: z.string(),
  posted: z.boolean(),
  timesheet_status: z.string().nullable(),
  posted_timesheet_hours: z.number(),
  posted_leave_hours: z.number(),
  recorded_timesheet_hours: z.number(),
  recorded_leave_hours: z.number(),
  matches: z.boolean(),
})
export type StaffWeekPosting = z.infer<typeof staffWeekPostingSchema>

/**
 * What Xero holds for the week, per staff member, beside what was recorded.
 *
 * Opus: This is the read-back an assertion about posting must use: checking that the
 * posting run reported success only proves the run agrees with itself.
 */
export async function getWeekPostingStatus(
  page: Page,
  weekStartDate: string,
): Promise<StaffWeekPosting[]> {
  const response = await page.request.get(
    `/api/timesheets/payroll/week-status/?week_start_date=${weekStartDate}`,
  )
  if (!response.ok()) {
    throw new Error(`Week status read failed: ${response.status()} ${await response.text()}`)
  }
  return z.object({ staff: z.array(staffWeekPostingSchema) }).parse(await response.json()).staff
}

const seededCostLineSchema = z.object({ id: z.string() })

/**
 * Record time for a staff member on a date, through the live cost-line create.
 *
 * Opus: ``meta.created_from_timesheet`` routes it through the one rate pipeline, so
 * unit cost/rev and the Xero pay item are server-derived exactly as a timesheet
 * write derives them — which is what makes the line safe to post to payroll.
 * Building the line by hand instead would prove Xero accepts a shape the
 * application never sends (ADR 0050).
 *
 * Opus: Seed onto a `[TEST]` job: `e2e_cleanup` deletes those and cascades to their
 * cost lines, while hours recorded against a restored production job survive
 * the reset and join every later payroll post for that week.
 */
export interface SeedTimesheetLabourPayload {
  jobId: string
  staffId: string
  labourSubtype: string
  date: string
  hours: number
  description: string
}

export async function seedTimesheetLabour(
  page: Page,
  payload: SeedTimesheetLabourPayload,
): Promise<string> {
  const response = await page.request.post(
    `/api/job/jobs/${payload.jobId}/cost_sets/actual/cost_lines/`,
    {
      data: {
        kind: 'time',
        desc: payload.description,
        quantity: payload.hours,
        accounting_date: payload.date,
        ext_refs: {},
        labour_subtype: payload.labourSubtype,
        meta: {
          created_from_timesheet: true,
          staff_id: payload.staffId,
          date: payload.date,
          is_billable: true,
          wage_rate_multiplier: 1,
        },
      },
    },
  )
  if (!response.ok()) {
    throw new Error(`Timesheet labour seed failed: ${response.status()} ${await response.text()}`)
  }
  return seededCostLineSchema.parse(await response.json()).id
}
