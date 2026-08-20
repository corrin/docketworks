import type { Page } from '@playwright/test'

import {
  getJobLabourRates,
  getPostableWeek,
  getTimesheetStaff,
  getWeekPostingStatus,
  refreshPayrollMirror,
  seedTimesheetLabour,
  type StaffWeekPosting,
} from '../fixtures/api'
import { test, expect } from '../fixtures/auth'
// The app's own date helpers, not a spec-local reimplementation: the fourth
// sibling copy of Monday arithmetic is how the three job pickers happened.
import { mondayOf, shiftDate } from '../../../src/lib/dates'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'
import { getLatestWeekdayDate } from './support'

/**
 * The weekly overview and its payroll controls.
 *
 * Opus: Authored, not ported: v1 has no spec for this screen. It asserts the two
 * things the screen exists for — seeing where the week's time went, and
 * getting it into Xero — plus the drill-downs that make it the same question
 * as the daily overview at a different zoom.
 *
 * Opus: **Posting is driven for real, and is opt-in.** Not because it is slow or
 * expensive, but because Xero Payroll NZ cannot undo it: `createPayRun` exists,
 * `updatePayRun` and `deletePayRun` do not, so posting a week leaves a draft
 * pay run that only a human can post or delete in the Xero UI. An unattended
 * gate must not accumulate external state nobody can clear, so those tests
 * carry @xero-payroll-write and are excluded unless E2E_XERO_PAYROLL=1
 * (`npm run test:e2e:payroll`). ADR 0050 names the exception and its condition.
 *
 * Opus: What that does NOT mean is that the write path went back to being checked
 * by a fake. This spec used to assert only the pay-run state machine and defer
 * the post to "the backend suite and manual checks", where the backend suite
 * substituted a fake provider — which can only confirm what its author already
 * assumed. The posting path is proven against the same real Xero before merge
 * by `apps/xero/tests/test_payroll_integration.py`.
 *
 * Opus: Payroll is sequential, by Xero's design: one draft pay run per calendar,
 * because you post the week ending the 9th, finalise it, and only then does
 * the 16th become postable. That is a deliberate limitation to reduce
 * mistakes, not an obstacle to route around. So the opt-in tests do what an
 * operator does — post the week the server names as postable, and re-post an
 * unfinalised draft, which is the ordinary move when a first post's outcome is
 * unclear. Reuse of the standing draft is what lets them run more than once.
 */

async function openWeek(page: Page, week: string): Promise<void> {
  await page.goto(`/timesheets/weekly?week=${week}`)
  // No networkidle: the page holds the payroll runs SSE stream open for its
  // whole life, so networkidle never fires — the same fact the kanban specs
  // record for the board's stream. The table is the readiness signal.
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

    // Opus: The footer total comes from the server's weekly_summary; v1 shipped a
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

    // Opus: Words, never an icon alone — the operator has to be able to read this
    // without decoding a colour.
    await expect(autoId(page, 'PayrollPanel-status')).toHaveText(
      /Pay run (ready for posting|locked \(already paid\)|not created yet)/,
    )
  })

  test('the postable week offers Post unless the week is already paid', async ({
    authenticatedPage: page,
  }) => {
    /**
     * Opus: This replaces an assertion that stopped describing the code at
     * `23de982`, when posting stopped requiring a draft to already exist. It
     * read "posting is refused until a draft pay run exists" and asserted the
     * button was disabled whenever the status was not "ready for posting" —
     * which is the state of a postable week with no run yet, where Post must be
     * OFFERED. It passed only because the demo tenant usually has a draft, so
     * the branch carrying the wrong assertion was rarely the branch taken.
     * The rule now is `busy || posted || !isPostableWeek`.
     */
    const postable = await getPostableWeek(page)
    await openWeek(page, postable)

    const status = await autoId(page, 'PayrollPanel-status').textContent()
    const postButton = autoId(page, 'PayrollPanel-postAll')

    if (status?.includes('locked')) {
      await expect(postButton, 'a paid week must not be postable again').toBeDisabled()
      return
    }
    await expect(
      postButton,
      `Post was withheld on ${postable}, the week the server calls postable, ` +
        `with the panel reporting "${status}". A run that does not exist yet is ` +
        'created by posting; it is not a precondition of it.',
    ).toBeEnabled()
  })

  test.describe('posting out of order', () => {
    // The 400 IS the assertion: the server refuses the wrong week by design,
    // and the browser reports every non-2xx as a console resource error.
    test.use({ expectedConsoleErrors: [/the server responded with a status of 400/] })

    test('is refused by the server, which names the postable week', async ({
      authenticatedPage: page,
    }) => {
      // Fable: The half that carries the money, enforced where it can be judged
      // on fresh data. The panel's banner reads a mirror that may be an hour
      // stale, so it advises rather than disables; the POST refreshes the mirror
      // itself and refuses, naming the week that CAN be posted. Clicking Post on
      // the wrong week must cost exactly a clear refusal — no run, no Xero
      // write.
      const farFuture = shiftDate(await getPostableWeek(page), 364)
      await openWeek(page, farFuture)

      await expect(autoId(page, 'PayrollPanel-notPostable')).toBeVisible()
      await expect(autoId(page, 'PayrollPanel-postAll')).toBeEnabled()
      await autoId(page, 'PayrollPanel-postAll').click()

      await expect(page.getByText(/can be posted next/)).toBeVisible({ timeout: 120000 })
      await expect(autoId(page, 'PayrollPanel-results')).toHaveCount(0)
    })
  })

  test('the banner on a far-past week walks the operator to the postable one', async ({
    authenticatedPage: page,
  }) => {
    const longAgo = mondayOf('2025-01-06')
    await openWeek(page, longAgo)

    await expect(autoId(page, 'PayrollPanel-notPostable')).toBeVisible()
    await autoId(page, 'PayrollPanel-goToPostableWeek').click()

    await expect(page).not.toHaveURL(new RegExp(`week=${longAgo}`))
    await expect(autoId(page, 'PayrollPanel-notPostable')).toHaveCount(0)
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
 * Opus: Navigates first rather than assuming the caller is still on the grid: job
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
  // Opus: The results list is driven by the SSE stream, so its arrival proves the
  // Celery task ran and reported per staff member — which neither half's unit
  // tests can show.
  await expect(autoId(page, 'PayrollPanel-results')).toBeVisible({ timeout: 870000 })
  await expect(autoId(page, 'PayrollPanel-postAll')).toBeEnabled({ timeout: 120000 })
}

test.describe('posting a week to Xero @xero-payroll-write', () => {
  // Opus: The panel posts every staff member — there is no per-staff control — and
  // the service sleeps 3s four times per employee to survive Xero's rate
  // limits, so a full staff list runs for minutes.
  test.setTimeout(900000)

  /**
   * Put the page in the state an operator posts from, and return the week.
   *
   * Fable: The week must be read AFTER a mirror refresh: teardown restores the
   * database out from under Xero, so the mirror's postable answer can name a
   * week Xero has moved past. Refreshing is a step of posting now — not a
   * button — so the fixture reaches it through the posting preflight's own
   * refusal contract.
   */
  async function openPostableWeek(page: Page): Promise<string> {
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

  test('hours recorded for the week reach Xero, and Xero holds what was recorded', async ({
    authenticatedPage: page,
  }) => {
    const week = await openPostableWeek(page)

    // Opus: Whoever the app lists for that day, NOT the E2E login user: payroll
    // requires a linked Xero employee, and `get_displayable_staff` drops
    // anyone without a UUID-shaped xero_user_id — which the E2E account has
    // none of. Hours seeded against it are hours nothing posts and the week
    // status never reports, so the assertions below would be measuring an
    // absence.
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
    // transmits nothing — while every assertion below still passes, on the
    // strength of a previous run's work. A test of a payroll write that goes
    // green while writing nothing is worse than no test.
    const seededHours = 2 + (Math.floor(Date.now() / 1000) % 60) / 100

    await seedTimesheetLabour(page, {
      jobId,
      staffId: staff.id,
      labourSubtype: labourRate.labour_subtype,
      // Opus: Tuesday: inside the week whichever way the week is configured.
      date: seedDate,
      hours: seededHours,
      description: '[TEST] payroll posting',
    })

    // Opus: Read the state the post has to change. The seeded hours are in our
    // database now and not yet in Xero, so these two MUST differ — if they
    // already agree, the post has nothing to do and proves nothing.
    const beforePosting = await getWeekPostingStatus(page, week)
    const seededRow = beforePosting.find((row) => row.staff_id === staff.id)
    const recordedAfterSeeding = seededRow?.recorded_timesheet_hours ?? 0
    const disagreedBeforePosting = seededRow !== undefined && !seededRow.matches

    await postWeek(page, week)

    // Opus: Read Xero back. Asserting the run reported success only proves the run
    // agrees with itself — exactly a mock's blind spot.
    const status = await getWeekPostingStatus(page, week)

    const seeded = status.find((row) => row.staff_id === staff.id)
    expect(
      seeded,
      'no week-status row for the staff member the hours were seeded for',
    ).toBeDefined()
    // Opus: Xero moved. Asserted as "disagreed before, agrees after" rather than as a
    // delta: posting REPLACES the timesheet, and teardown restores our database
    // but not Xero's, so before this run Xero holds a previous run's total. The
    // arithmetic difference is therefore newSeed MINUS oldSeed, and an assertion
    // expecting newSeed fails on every run after the first. The unique seed is
    // what guarantees the two disagreed to begin with.
    expect(
      disagreedBeforePosting,
      `Xero already held exactly the hours this run recorded (${recordedAfterSeeding}h), so the ` +
        'post could have transmitted nothing and every assertion below would still pass.',
    ).toBe(true)
    expect(
      seeded!.matches,
      `after posting, Xero holds ${seeded!.posted_timesheet_hours}h worked / ` +
        `${seeded!.posted_leave_hours}h leave against the timesheet's ` +
        `${seeded!.recorded_timesheet_hours}h / ${seeded!.recorded_leave_hours}h`,
    ).toBe(true)

    // Opus: UNDERPAID: recorded hours that reached no timesheet at all. Checking only
    // the staff Xero holds a timesheet for would pass this silently — a person
    // skipped by the run looks identical to a person with nothing to post, and
    // the difference is whether they are paid this week.
    const unposted = status.filter((row) => !row.posted && recordedHours(row) > 0)
    expect(
      unposted.map((row) => `${row.staff_id}: ${recordedHours(row)}h recorded, nothing in Xero`),
      'staff have recorded hours that never reached Xero',
    ).toEqual([])

    // Opus: MISPAID: Xero holds a different figure from the timesheet, on either
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
    // Opus: The move an operator makes when a post's outcome is unclear: post again.
    // ADR 0007 promises replacement, and the failure it hides is Xero holding
    // both figures — which pays twice.
    const week = await openPostableWeek(page)
    await postWeek(page, week)
    const before = await getWeekPostingStatus(page, week)

    await postWeek(page, week)

    const after = await getWeekPostingStatus(page, week)

    // Opus: Collected and counted before anything is compared. A bare loop over the
    // rows asserts nothing when no row is posted both times — the test passes
    // loudest exactly when both posts failed. And a row holding zero hours
    // cannot distinguish replacement from addition, because zero plus zero is
    // still zero, so the pair must carry hours to be evidence of anything.
    const comparable = after
      .filter((row) => row.posted)
      .map((row) => ({ row, previous: before.find((prior) => prior.staff_id === row.staff_id) }))
      .filter(({ previous }) => previous?.posted)
      .filter(({ row }) => row.posted_timesheet_hours > 0 || row.posted_leave_hours > 0)
    expect(
      comparable.length,
      'no staff member was posted with hours both before and after the re-post, ' +
        'so this test compared nothing',
    ).toBeGreaterThan(0)

    for (const { row, previous } of comparable) {
      expect(
        row.posted_timesheet_hours,
        `staff ${row.staff_id} went from ${previous?.posted_timesheet_hours}h to ` +
          `${row.posted_timesheet_hours}h on an unchanged re-post`,
      ).toBe(previous?.posted_timesheet_hours)
      expect(row.posted_leave_hours).toBe(previous?.posted_leave_hours)
    }
  })

  test('the panel reports whether Xero agrees, and only when asked', async ({
    authenticatedPage: page,
  }) => {
    await openPostableWeek(page)

    // Opus: Not on load: the read costs one Xero call per staff member.
    await expect(autoId(page, 'PayrollPanel-inSync')).toHaveCount(0)
    await expect(autoId(page, 'PayrollPanel-outOfSync')).toHaveCount(0)

    await autoId(page, 'PayrollPanel-checkXero').click()

    await expect(
      autoId(page, 'PayrollPanel-inSync').or(autoId(page, 'PayrollPanel-outOfSync')).first(),
    ).toBeVisible({ timeout: 300000 })
    // Opus: Never the "could not read" branch: that means the endpoint failed, and
    // the panel would be showing recorded hours with no Xero behind them.
    await expect(autoId(page, 'PayrollPanel-statusUnavailable')).toHaveCount(0)
  })
})
