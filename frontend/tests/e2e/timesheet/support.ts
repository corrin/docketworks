/** Shared setup for the timesheet-entry cluster (one implementation per concept). */
import type { Page } from '@playwright/test'
import { shiftDate } from '../../../src/lib/dates'
import {
  getJobLabourRates,
  getTimesheetStaff,
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

/**
 * Hours on a [TEST] job for one linked staff member inside a payroll week.
 *
 * The weekly-payroll post and the payroll reconciliation both need a week
 * that holds DocketWorks time: the post so it has something to transmit,
 * the reconciliation so the loaded and base figures are dollars, not $0.00
 * twice. The postable week moves forward with every posted run, so a week
 * with restored time cannot be relied on; the spec seeds its own.
 */
export async function seedLabourForWeek(
  page: Page,
  week: string,
): Promise<{ staff: TimesheetStaff; hours: number }> {
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
  const hours = 2 + (Math.floor(Date.now() / 1000) % 60) / 100

  await seedTimesheetLabour(page, {
    jobId,
    staffId: staff.id,
    labourSubtype: labourRate.labour_subtype,
    date: seedDate,
    hours,
    description: '[TEST] payroll posting',
  })
  return { staff, hours }
}
