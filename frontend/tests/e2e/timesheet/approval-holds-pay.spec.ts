/**
 * Staff are paid for approved time only (KAN-376). A worker's own entry
 * arrives unapproved: the weekly screen names it as held back until the
 * office approves it, and a post leaves it out until then.
 *
 * The worker's line is written by the workshop login, in its own browser
 * context, because who wrote a line is what decides whether it starts
 * approved. It is booked to a staff member payroll knows, since the workshop
 * E2E login has no Xero employee and nothing of its own is ever posted.
 */
import type { Browser } from '@playwright/test'
import { z } from 'zod'

import { getWeekPostingStatus, seedTimesheetLabour } from '../fixtures/api'
import { authenticateViaLoginPage, e2eCredentials, expect, test } from '../fixtures/auth'
import { mondayOf } from '../../../src/lib/dates'
import { autoId } from '../helpers'
import {
  getLatestWeekdayDate,
  openPostableWeek,
  openWeek,
  postWeek,
  seedLabourForWeek,
  type SeededLabour,
} from './support'

/** Hours no other seed uses, so the held-back figure can only be this line. */
const WORKER_HOURS = 1.25

/** Book time as the workshop login would: it arrives unapproved. */
async function bookAsWorkshopUser(
  browser: Browser,
  baseURL: string,
  seeded: SeededLabour,
): Promise<string> {
  const context = await browser.newContext({ baseURL })
  try {
    const page = await context.newPage()
    const { username, password } = e2eCredentials('workshop')
    await authenticateViaLoginPage(page, username, password, () => () => undefined)
    return await seedTimesheetLabour(page, {
      jobId: seeded.jobId,
      staffId: seeded.staff.id,
      labourSubtype: seeded.labourSubtype,
      date: seeded.date,
      hours: WORKER_HOURS,
      description: '[TEST] waiting for approval',
    })
  } finally {
    await context.close()
  }
}

test.describe('approval holds pay', () => {
  test('the weekly screen names unapproved hours until the office approves them', async ({
    authenticatedPage: page,
    browser,
    baseURL,
  }) => {
    const week = mondayOf(getLatestWeekdayDate())
    const seeded = await seedLabourForWeek(page, week)
    const staffId = seeded.staff.id
    const heldBack = autoId(page, `WeeklyOverview-heldBack-${staffId}`)

    await openWeek(page, week)
    const heldBackBefore = await heldBack.innerText()

    const waitingLineId = await bookAsWorkshopUser(browser, z.string().parse(baseURL), seeded)

    await openWeek(page, week)
    await expect(heldBack).not.toHaveText(heldBackBefore)
    await expect(heldBack).toContainText('h')
    // The panel names people as the weekly table does, so read the name there.
    const weekly = z
      .object({ staff_data: z.array(z.object({ staff_id: z.string(), staff_name: z.string() })) })
      .parse(await (await page.request.get(`/api/timesheets/weekly/?start_date=${week}`)).json())
    const staffName = weekly.staff_data.find((row) => row.staff_id === staffId)?.staff_name
    expect(staffName, 'the seeded staff member is on the weekly screen').toBeDefined()
    await expect(autoId(page, 'PayrollPanel-heldBack')).toContainText(z.string().parse(staffName))

    const approval = await page.request.post(`/api/job/cost_lines/${waitingLineId}/approve/`)
    expect(approval.ok(), await approval.text()).toBe(true)

    await openWeek(page, week)
    await expect(heldBack).toHaveText(heldBackBefore)
  })
})

// Opt-in, like every post: Xero Payroll NZ cannot undo one (see
// weekly-payroll.spec.ts), and the fake does not route payroll writes.
test.describe('approval holds pay at the post @xero-payroll-write', () => {
  // Two posts of every staff member, at the pace Xero's limits allow.
  test.setTimeout(1800000)

  test('unapproved time is left out of the post until the office approves it', async ({
    authenticatedPage: page,
    browser,
    baseURL,
  }) => {
    const week = await openPostableWeek(page)
    const seeded = await seedLabourForWeek(page, week)
    const staffId = seeded.staff.id
    const rowFor = async () => {
      const row = (await getWeekPostingStatus(page, week)).find((each) => each.staff_id === staffId)
      if (row === undefined) throw new Error(`No week-status row for staff ${staffId}`)
      return row
    }
    const approvedOnly = (await rowFor()).recorded_timesheet_hours

    const waitingLineId = await bookAsWorkshopUser(browser, z.string().parse(baseURL), seeded)

    await test.step('the post sends the approved hours and leaves the rest', async () => {
      expect(
        (await rowFor()).recorded_timesheet_hours,
        'unapproved time must not count as recorded for payroll',
      ).toBe(approvedOnly)
      await postWeek(page, week)
      const posted = await rowFor()
      expect(posted.posted_timesheet_hours).toBe(approvedOnly)
      expect(posted.matches).toBe(true)
    })

    await test.step('approving the entry is what releases it', async () => {
      const approval = await page.request.post(`/api/job/cost_lines/${waitingLineId}/approve/`)
      expect(approval.ok(), await approval.text()).toBe(true)
      const approved = await rowFor()
      expect(approved.recorded_timesheet_hours).toBeCloseTo(approvedOnly + WORKER_HOURS, 2)
      expect(approved.matches, 'Xero still holds the earlier post').toBe(false)
    })

    await test.step('the next post pays it', async () => {
      await postWeek(page, week)
      const reposted = await rowFor()
      expect(reposted.posted_timesheet_hours).toBeCloseTo(approvedOnly + WORKER_HOURS, 2)
      expect(reposted.matches).toBe(true)
    })
  })
})
