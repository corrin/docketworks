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
  email: z.string(),
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
  email: z.string(),
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
