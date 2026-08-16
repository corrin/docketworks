import type { Page } from '@playwright/test'

import {
  getJobLabourRates,
  getPostableWeek,
  getTimesheetStaff,
  getWeekPostingStatus,
  seedTimesheetLabour,
  type StaffWeekPosting,
} from '../fixtures/api'
import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'
import { getLatestWeekdayDate } from './support'

/**
 * The weekly overview and its payroll controls.
 *
 * Authored, not ported: v1 has no spec for this screen. It asserts the two
 * things the screen exists for — seeing where the week's time went, and
 * getting it into Xero — plus the drill-downs that make it the same question
 * as the daily overview at a different zoom.
 *
 * **Posting is driven for real, every run.** This spec used to assert only the
 * pay-run state machine and leave the post itself to "the backend suite and
 * manual checks against the demo company" — but the backend suite substitutes
 * a fake provider, which can only confirm what its author already assumed, and
 * a manual check is not a test. The suite hits real services (see
 * `frontend/docs/e2e-testing-strategy.md`), and payroll was the one write path
 * exempting itself.
 *
 * Payroll is sequential, by Xero's design: one draft pay run per calendar,
 * because you post the week ending the 9th, finalise it, and only then does
 * the 16th become postable. That is a deliberate limitation to reduce
 * mistakes, not an obstacle to route around. So this spec does what an
 * operator does — posts the week the server names as postable, and re-posts an
 * unfinalised draft, which is the ordinary move when a first post's outcome is
 * unclear. Reuse of the standing draft is what makes it re-runnable, and it is
 * ordinary operation rather than a concession.
 */

/** Parse a YYYY-MM-DD as a LOCAL date; `new Date(iso)` would read it as UTC. */
function localDate(isoDate: string): Date {
  const parts = isoDate.split('-')
  if (parts.length !== 3) throw new Error(`Not a YYYY-MM-DD date: ${isoDate}`)
  return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
}

function formatIso(date: Date): string {
  const paddedMonth = String(date.getMonth() + 1).padStart(2, '0')
  const paddedDay = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${paddedMonth}-${paddedDay}`
}

/** The Monday of the week containing the given date, in local terms. */
function mondayOf(isoDate: string): string {
  const date = localDate(isoDate)
  const weekday = date.getDay()
  date.setDate(date.getDate() - weekday + (weekday === 0 ? -6 : 1))
  return formatIso(date)
}

/** The date `days` after the given one. */
function shiftIsoDate(isoDate: string, days: number): string {
  const date = localDate(isoDate)
  date.setDate(date.getDate() + days)
  return formatIso(date)
}

async function openWeek(page: Page, week: string): Promise<void> {
  await page.goto(`/timesheets/weekly?week=${week}`)
  await page.waitForLoadState('networkidle')
  await autoId(page, 'WeeklyOverview-table').waitFor({ timeout: 30000 })
}

test.describe('weekly timesheets', () => {
  const week = mondayOf(getLatestWeekdayDate())

  test('shows the week for every staff member, with server totals', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    const rows = page.locator('[data-automation-id^="WeeklyOverview-row-"]')
    expect(await rows.count()).toBeGreaterThan(0)

    // The footer total comes from the server's weekly_summary; v1 shipped a
    // client-side recomputation alongside it and showed the client's.
    await expect(autoId(page, 'WeeklyOverview-totalHours')).toContainText('h')
  })

  test('a day header drills into that day, and a cell into that staff member’s entries', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    const firstHeader = page.locator('[data-automation-id^="WeeklyOverview-dayHeader-"]').first()
    const headerId = await firstHeader.getAttribute('data-automation-id')
    const day = headerId!.replace('WeeklyOverview-dayHeader-', '')
    await firstHeader.click()
    await page.waitForURL(`**/timesheets/daily**date=${day}**`)

    await openWeek(page, week)
    const firstCell = page.locator('[data-automation-id^="WeeklyOverview-cell-"]').first()
    await firstCell.click()
    await page.waitForURL('**/timesheets/entry**')
  })

  test('a staff row expands into its payroll categories', async ({ authenticatedPage: page }) => {
    await openWeek(page, week)

    const toggle = page.locator('[data-automation-id^="WeeklyOverview-expand-"]').first()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  })

  test('the payroll panel states the week’s pay-run position', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    // Words, never an icon alone — the operator has to be able to read this
    // without decoding a colour.
    await expect(autoId(page, 'PayrollPanel-status')).toHaveText(
      /Pay run (ready for posting|locked \(already paid\)|not created yet)/,
    )
  })

  test('posting is refused until a draft pay run exists for the week', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    const status = await autoId(page, 'PayrollPanel-status').textContent()
    const postButton = autoId(page, 'PayrollPanel-postAll')

    if (status?.includes('ready for posting')) {
      await expect(postButton).toBeEnabled()
    } else {
      // No run, or a locked one: either way the hours cannot go anywhere yet.
      await expect(postButton).toBeDisabled()
    }
  })

  test('a far-past week offers no pay-run creation and says why', async ({
    authenticatedPage: page,
  }) => {
    // Xero processes pay runs in sequence, so a week well before the postable
    // one must not offer to create a run out of order.
    const longAgo = mondayOf('2025-01-06')
    await openWeek(page, longAgo)

    await expect(autoId(page, 'PayrollPanel-notPostable')).toBeVisible()
    await expect(autoId(page, 'PayrollPanel-createPayRun')).toHaveCount(0)
    await expect(autoId(page, 'PayrollPanel-postAll')).toBeDisabled()
  })

  test('week navigation moves the grid and the payroll panel together', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)
    const firstRange = await autoId(page, 'WeeklyOverview-range').textContent()

    await page.getByRole('button', { name: 'Previous week' }).click()
    await autoId(page, 'WeeklyOverview-table').waitFor({ timeout: 30000 })

    await expect(autoId(page, 'WeeklyOverview-range')).not.toHaveText(firstRange!)
    await expect(autoId(page, 'PayrollPanel-status')).toBeVisible()
  })
})

/** Everything the timesheet holds for a staff member's week, both surfaces. */
function recordedHours(row: StaffWeekPosting): number {
  return row.recorded_timesheet_hours + row.recorded_leave_hours
}

/**
 * Open the week and post it, then wait for the SSE run to finish reporting.
 *
 * Navigates first rather than assuming the caller is still on the grid: job
 * creation and entry both leave the page, and clicking a button that is not on
 * screen simply waits — this test once burned its whole 15-minute budget doing
 * exactly that, with nothing in the log but a timeout.
 */
async function postWeek(page: Page, week: string): Promise<void> {
  await openWeek(page, week)
  await expect(
    autoId(page, 'PayrollPanel-postAll'),
    `Post is not available on ${week}; its title names the unmet precondition.`,
  ).toBeEnabled({ timeout: 120000 })
  await autoId(page, 'PayrollPanel-postAll').click()
  // The results list is driven by the SSE stream, so its arrival proves the
  // Celery task ran and reported per staff member — which neither half's unit
  // tests can show.
  await expect(autoId(page, 'PayrollPanel-results')).toBeVisible({ timeout: 870000 })
  await expect(autoId(page, 'PayrollPanel-postAll')).toBeEnabled({ timeout: 120000 })
}

test.describe('posting a week to Xero', () => {
  // The panel posts every staff member — there is no per-staff control — and
  // the service sleeps 3s four times per employee to survive Xero's rate
  // limits, so a full staff list runs for minutes.
  test.setTimeout(900000)

  /**
   * Put the page in the state an operator posts from, and return the week.
   *
   * "Refresh from Xero" is not ceremony, and its ORDER is load-bearing.
   * Teardown restores the database, so the local XeroPayRun mirror comes back
   * without pay runs Xero still holds — and the postable week is computed from
   * that mirror. Asking which week is postable before refreshing therefore
   * answers from stale data, and the refresh then moves the answer out from
   * under the week already open: the page shows a week with no pay run,
   * offering neither Create (not the postable week) nor Post.
   */
  async function openPostableWeek(page: Page): Promise<string> {
    // Any week will do to reach the panel; the refresh is calendar-wide.
    await openWeek(page, mondayOf(getLatestWeekdayDate()))

    // Wait on the RESPONSE, not on the button. The button is only disabled
    // while the request is in flight, so `toBeEnabled` is satisfied by the
    // state before the click as readily as the state after it — and reading
    // the postable week against a half-synced mirror is how this test last
    // navigated to a week the panel then called unpostable.
    const refreshed = page.waitForResponse(
      (response) =>
        response.url().includes('/api/timesheets/payroll/pay-runs/refresh') &&
        response.request().method() === 'POST',
      { timeout: 120000 },
    )
    await autoId(page, 'PayrollPanel-refresh').click()
    const refreshResponse = await refreshed
    if (!refreshResponse.ok()) {
      throw new Error(
        `Refreshing the pay-run mirror failed: ${refreshResponse.status()} ` +
          (await refreshResponse.text()),
      )
    }

    const week = await getPostableWeek(page)
    await openWeek(page, week)

    if ((await autoId(page, 'PayrollPanel-createPayRun').count()) > 0) {
      await autoId(page, 'PayrollPanel-createPayRun').click()
    }
    await expect(
      autoId(page, 'PayrollPanel-postAll'),
      `Post stayed disabled on ${week}, the week the server calls postable. ` +
        'Read the button title: it names which precondition is unmet.',
    ).toBeEnabled({ timeout: 120000 })
    return week
  }

  test('hours recorded for the week reach Xero, and Xero holds what was recorded', async ({
    authenticatedPage: page,
  }) => {
    const week = await openPostableWeek(page)

    // Whoever the app lists for that day, NOT the E2E login user: payroll
    // requires a linked Xero employee, and `get_displayable_staff` drops
    // anyone without a UUID-shaped xero_user_id — which the E2E account has
    // none of. Hours seeded against it are hours nothing posts and the week
    // status never reports, so the assertions below would be measuring an
    // absence.
    const seedDate = shiftIsoDate(week, 1)
    const candidates = await getTimesheetStaff(page, seedDate)
    const staff = candidates[0]
    if (staff === undefined) {
      throw new Error(
        `No staff are available for timesheet entry on ${seedDate}, so no hours can be ` +
          'seeded for the postable week. Check the restore linked staff to Xero employees.',
      )
    }

    // Seed onto a [TEST] job so e2e_cleanup cascades the line away; hours left
    // on a restored production job would join every later post of this week.
    const jobUrl = await createTestJob(page, 'Payroll')
    const jobId = getJobIdFromUrl(jobUrl)
    const labourRates = await getJobLabourRates(page, jobId)
    const labourRate = labourRates[0]
    if (labourRate === undefined) {
      throw new Error(`Job ${jobId} has no labour rates; a time line cannot be priced.`)
    }
    // A quantity no previous run can already have posted. Teardown restores OUR
    // database but not Xero's, so a fixed amount is re-seeded identically every
    // run, the posting path detects "already matches the hours to post" and
    // transmits nothing — while every assertion below still passes, on the
    // strength of a previous run's work. A test of a payroll write that goes
    // green while writing nothing is worse than no test.
    const seededHours = 2 + ((Date.now() / 1000) % 60) / 100
    const before = await getWeekPostingStatus(page, week)
    const postedBefore =
      before.find((row) => row.staff_id === staff.id)?.posted_timesheet_hours ?? 0

    await seedTimesheetLabour(page, {
      jobId,
      staffId: staff.id,
      labourSubtype: labourRate.labour_subtype,
      // Tuesday: inside the week whichever way the week is configured.
      date: seedDate,
      hours: seededHours,
      description: '[TEST] payroll posting',
    })

    await postWeek(page, week)

    // Read Xero back. Asserting the run reported success only proves the run
    // agrees with itself — exactly a mock's blind spot.
    const status = await getWeekPostingStatus(page, week)

    const seeded = status.find((row) => row.staff_id === staff.id)
    expect(
      seeded,
      'no week-status row for the staff member the hours were seeded for',
    ).toBeDefined()
    // Xero moved, by exactly the hours this run added. Without this the suite
    // cannot tell a real post from a no-op against a tenant a previous run
    // already left in the right state.
    expect(
      seeded!.posted_timesheet_hours - postedBefore,
      `Xero held ${postedBefore}h for staff ${staff.id} before this run and ` +
        `${seeded!.posted_timesheet_hours}h after, but ${seededHours}h were seeded — ` +
        'this run posted nothing.',
    ).toBeCloseTo(seededHours, 2)

    // UNDERPAID: recorded hours that reached no timesheet at all. Checking only
    // the staff Xero holds a timesheet for would pass this silently — a person
    // skipped by the run looks identical to a person with nothing to post, and
    // the difference is whether they are paid this week.
    const unposted = status.filter((row) => !row.posted && recordedHours(row) > 0)
    expect(
      unposted.map((row) => `${row.staff_id}: ${recordedHours(row)}h recorded, nothing in Xero`),
      'staff have recorded hours that never reached Xero',
    ).toEqual([])

    // MISPAID: Xero holds a different figure from the timesheet, on either
    // surface. Compared per surface because an equal total can still hide
    // leave posted as worked time, which pays the same and never debits the
    // leave balance.
    const mismatched = status.filter((row) => row.posted && !row.matches)
    expect(
      mismatched.map(
        (row) =>
          `${row.staff_id}: Xero ${row.posted_timesheet_hours}h worked / ` +
          `${row.posted_leave_hours}h leave vs timesheet ${row.recorded_timesheet_hours}h / ` +
          `${row.recorded_leave_hours}h`,
      ),
      'Xero disagrees with the timesheet',
    ).toEqual([])
  })

  test('re-posting replaces the hours in Xero rather than adding to them', async ({
    authenticatedPage: page,
  }) => {
    // The move an operator makes when a post's outcome is unclear: post again.
    // ADR 0007 promises replacement, and the failure it hides is Xero holding
    // both figures — which pays twice.
    const week = await openPostableWeek(page)
    await postWeek(page, week)
    const before = await getWeekPostingStatus(page, week)

    await postWeek(page, week)

    const after = await getWeekPostingStatus(page, week)
    for (const row of after.filter((candidate) => candidate.posted)) {
      const previous = before.find((candidate) => candidate.staff_id === row.staff_id)
      if (!previous?.posted) continue
      expect(
        row.posted_timesheet_hours,
        `staff ${row.staff_id} went from ${previous.posted_timesheet_hours}h to ` +
          `${row.posted_timesheet_hours}h on an unchanged re-post`,
      ).toBe(previous.posted_timesheet_hours)
      expect(row.posted_leave_hours).toBe(previous.posted_leave_hours)
    }
  })

  test('the panel reports whether Xero agrees, and only when asked', async ({
    authenticatedPage: page,
  }) => {
    await openPostableWeek(page)

    // Not on load: the read costs one Xero call per staff member.
    await expect(autoId(page, 'PayrollPanel-inSync')).toHaveCount(0)
    await expect(autoId(page, 'PayrollPanel-outOfSync')).toHaveCount(0)

    await autoId(page, 'PayrollPanel-checkXero').click()

    await expect(
      autoId(page, 'PayrollPanel-inSync').or(autoId(page, 'PayrollPanel-outOfSync')).first(),
    ).toBeVisible({ timeout: 300000 })
    // Never the "could not read" branch: that means the endpoint failed, and
    // the panel would be showing recorded hours with no Xero behind them.
    await expect(autoId(page, 'PayrollPanel-statusUnavailable')).toHaveCount(0)
  })
})
