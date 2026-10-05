/** Shared setup for the timesheet-entry cluster (one implementation per concept). */
import type { Page } from '@playwright/test'
import { shiftDate } from '../../../src/lib/dates'
import {
  getJobLabourRates,
  getPostableWeek,
  getTimesheetStaff,
  refreshPayrollMirror,
  seedTimesheetLabour,
  type TimesheetStaff,
} from '../fixtures/api'
import { expect } from '../fixtures/auth'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'

/**
 * Today's local date as YYYY-MM-DD, shifted back to Friday on a weekend —
 * every timesheet spec drives its date off this (v1 dateUtils rule: never
 * toISOString, which shifts NZ dates through UTC).
 */
export function getLatestWeekdayDate(): string {
  const now = new Date()
  const day = now.getDay()
  if (day === 6) now.setDate(now.getDate() - 1)
  if (day === 0) now.setDate(now.getDate() - 2)
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const date = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${date}`
}

/** The freshly created job's number, read off the job view header. */
export async function readJobNumber(page: Page): Promise<number> {
  const text = await autoId(page, 'JobView-job-number').first().innerText()
  const match = /#(\d+)/.exec(text)
  if (!match) throw new Error(`Job number not found in header text: ${text}`)
  return Number(match[1])
}

/** Daily page → click the first staff row → land on the entry page. */
export async function openEntryViaDaily(page: Page, date: string): Promise<void> {
  await page.goto(`/timesheets/daily?date=${date}`)
  const firstStaff = page.locator('[data-automation-id^="StaffRow-name-"]').first()
  await firstStaff.waitFor({ timeout: 15000 })
  await firstStaff.click()
  await page.waitForURL('**/timesheets/entry**')
  await waitForEntryGrid(page)
}

/** The grid is interactable once it renders and the loading spinner is gone. */
export async function waitForEntryGrid(page: Page): Promise<void> {
  await page.locator('.smart-timesheet-table').waitFor({ state: 'visible', timeout: 60000 })
  await page.waitForFunction(() => !document.querySelector('.animate-spin'), { timeout: 60000 })
}

/** Open row N's job picker and select a job by its number. */
export async function selectJobByNumber(
  page: Page,
  rowIndex: number,
  jobNumber: number | string,
): Promise<void> {
  const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-search`)
  if (!(await search.isVisible())) {
    await autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`).click()
  }
  await expect(search).toBeFocused()
  await search.fill(String(jobNumber))
  const option = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-option-${jobNumber}`)
  await option.waitFor({ timeout: 10000 })
  await option.click()
}

/** Type hours into row N and press Enter (the immediate-create gesture). */
export async function enterHours(page: Page, rowIndex: number, hours: string): Promise<void> {
  const input = autoId(page, `SmartTimesheetTable-hours-${rowIndex}`)
  await input.click()
  await page.keyboard.type(hours)
  await page.keyboard.press('Enter')
}

/** What `seedLabourForWeek` booked, with enough to book more beside it. */
export interface SeededLabour {
  staff: TimesheetStaff
  hours: number
  jobId: string
  labourSubtype: string
  date: string
}

/**
 * Hours on a [TEST] job for one linked staff member inside a payroll week.
 *
 * The weekly-payroll post and the payroll reconciliation both need a week
 * that holds DocketWorks time: the post so it has something to transmit,
 * the reconciliation so the loaded and base figures are dollars, not $0.00
 * twice. The postable week moves forward with every posted run, so a week
 * with restored time cannot be relied on; the spec seeds its own.
 */
export async function seedLabourForWeek(page: Page, week: string): Promise<SeededLabour> {
  // Opus: Whoever the app lists for that day, NOT the E2E login user: payroll
  // requires a linked Xero employee, and `get_displayable_staff` drops
  // anyone without a UUID-shaped xero_user_id — which the E2E account has
  // none of. Hours seeded against it are hours nothing posts and the week
  // status never reports, so the assertions would be measuring an absence.
  // Tuesday: inside the week whichever way the week is configured.
  const seedDate = shiftDate(week, 1)
  const candidates = await getTimesheetStaff(page, seedDate)
  const staff = candidates[0]
  if (staff === undefined) {
    throw new Error(
      `No staff are available for timesheet entry on ${seedDate}, so no hours can be ` +
        'seeded for the postable week. Check the restore linked staff to Xero employees.',
    )
  }

  // Opus: Seed onto a [TEST] job so e2e_cleanup cascades the line away; hours left
  // on a restored production job would join every later post of this week.
  const jobUrl = await createTestJob(page, 'Payroll')
  const jobId = getJobIdFromUrl(jobUrl)
  const labourRates = await getJobLabourRates(page, jobId)
  const labourRate = labourRates[0]
  if (labourRate === undefined) {
    throw new Error(`Job ${jobId} has no labour rates; a time line cannot be priced.`)
  }
  // Opus: A quantity no previous run can already have posted. Teardown restores OUR
  // database but not Xero's, so a fixed amount is re-seeded identically every
  // run, the posting path detects "already matches the hours to post" and
  // transmits nothing — while every assertion still passes, on the strength
  // of a previous run's work. A test of a payroll write that goes green while
  // writing nothing is worse than no test.
  // Whole hundredths divided once: 2 + 0.57 is 2.5700000000000003 in floating
  // point, sixteen digits, and the server refuses a quantity over ten.
  const hours = (200 + (Math.floor(Date.now() / 1000) % 60)) / 100

  await seedTimesheetLabour(page, {
    jobId,
    staffId: staff.id,
    labourSubtype: labourRate.labour_subtype,
    date: seedDate,
    hours,
    description: '[TEST] payroll posting',
  })
  return { staff, hours, jobId, labourSubtype: labourRate.labour_subtype, date: seedDate }
}

/** Open the weekly screen on a week; the table is the readiness signal. */
export async function openWeek(page: Page, week: string): Promise<void> {
  await page.goto(`/timesheets/weekly?week=${week}`)
  // No networkidle: the page holds the payroll runs SSE stream open for its
  // whole life, so networkidle never fires — the same fact the kanban specs
  // record for the board's stream.
  await autoId(page, 'WeeklyOverview-table').waitFor({ timeout: 30000 })
}

/**
 * Open the week and post it, then wait for the SSE run to finish reporting.
 *
 * Opus: Navigates first rather than assuming the caller is still on the grid: job
 * creation and entry both leave the page, and clicking a button that is not on
 * screen simply waits — this test once burned its whole 15-minute budget doing
 * exactly that, with nothing in the log but a timeout.
 */
export async function postWeek(page: Page, week: string): Promise<void> {
  await openWeek(page, week)
  await expect(
    autoId(page, 'PayrollPanel-postAll'),
    `Post is not available on ${week}; its title names the unmet precondition.`,
  ).toBeEnabled({ timeout: 120000 })
  await autoId(page, 'PayrollPanel-postAll').click()
  // Opus: The results list is driven by the SSE stream, so its arrival proves the
  // Celery task ran and reported per staff member — which neither half's unit
  // tests can show.
  await expect(autoId(page, 'PayrollPanel-results')).toBeVisible({ timeout: 870000 })
  await expect(autoId(page, 'PayrollPanel-postAll')).toBeEnabled({ timeout: 120000 })
}

/**
 * Put the page in the state an operator posts from, and return the week.
 *
 * Fable: The week must be read AFTER a mirror refresh: teardown restores the
 * database out from under Xero, so the mirror's postable answer can name a
 * week Xero has moved past. Refreshing is a step of posting now — not a
 * button — so the fixture reaches it through the posting preflight's own
 * refusal contract.
 */
export async function openPostableWeek(page: Page): Promise<string> {
  await refreshPayrollMirror(page)
  const week = await getPostableWeek(page)
  await openWeek(page, week)
  await expect(
    autoId(page, 'PayrollPanel-postAll'),
    `Post stayed disabled on ${week}, the week the server calls postable. ` +
      'Read the button title: it names which precondition is unmet.',
  ).toBeEnabled({ timeout: 120000 })
  return week
}
