/**
 * The General work sweep (KAN-380): clocked time that is on no job goes onto
 * the General work job when the office sweeps, and sweeping approves the day.
 * Driven as an office user who is not a superuser, as Approve time is.
 *
 * The person's day is set up by the logins whose job that is: the superuser
 * seeds hours on a job, the workshop login books an entry that waits, and the
 * office sets the clock times on Approve time.
 */
import type { Browser, Page } from '@playwright/test'
import { z } from 'zod'

import { mondayOf, shiftDate } from '../../../src/lib/dates'
import { formatHoursDisplay } from '../../../src/lib/format'
import { authenticateViaLoginPage, e2eCredentials, expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'
import {
  bookAsWorkshopUser,
  getLatestWeekdayDate,
  seedLabourForWeek,
  type SeededLabour,
} from './support'

/**
 * 06:30 to 15:00 with the standard breaks the office's times put on the day:
 * 8h 30m here, less the 30m unpaid lunch. The paid breaks are hours entered.
 */
const CLOCK_IN = '06:30'
const CLOCK_OUT = '15:00'
const PAID_HOURS_CLOCKED = 8

/**
 * Five weeks ahead. The dev database is a production restore, so a past day
 * holds real time; the suite restores the database after every run, so a
 * future week is empty each time, and clear of the current week the other
 * timesheet specs book on.
 */
const FUTURE_WEEK = shiftDate(mondayOf(getLatestWeekdayDate()), 35)

const approvals = z.object({
  staff: z.array(
    z.object({
      staff_id: z.string(),
      entered_hours: z.number(),
      clock: z.object({ state: z.string() }),
    }),
  ),
})

/**
 * What a sweep should move: the paid time clocked less everything entered.
 * Read from the person's entered hours, a figure the sweep does not compute,
 * because the dev database is a production restore and may hold real entries.
 */
async function expectedSweep(page: Page, day: string, staffId: string): Promise<number> {
  const body = approvals.parse(
    await (await page.request.get(`/api/timesheets/approvals/?date=${day}`)).json(),
  )
  const person = body.staff.find((each) => each.staff_id === staffId)
  if (person === undefined) throw new Error(`${staffId} is not on the timesheet for ${day}.`)
  const hours = Math.round((PAID_HOURS_CLOCKED - person.entered_hours) * 100) / 100
  if (hours <= 0) throw new Error(`${staffId} already has ${person.entered_hours}h on ${day}.`)
  return hours
}

async function seedAsSuperuser(
  browser: Browser,
  baseURL: string,
  week: string,
): Promise<SeededLabour> {
  const context = await browser.newContext({ baseURL })
  try {
    const page = await context.newPage()
    const { username, password } = e2eCredentials('office')
    await authenticateViaLoginPage(page, username, password, () => () => undefined)
    return await seedLabourForWeek(page, week)
  } finally {
    await context.close()
  }
}

async function setClock(page: Page, staffId: string): Promise<void> {
  await autoId(page, `ApproveTimePage-open-${staffId}`).click()
  await autoId(page, `ApproveTimePage-clock-edit-${staffId}`).click()
  await autoId(page, `ApproveTimePage-clock-${staffId}-start`).fill(CLOCK_IN)
  await autoId(page, `ApproveTimePage-clock-${staffId}-finish`).fill(CLOCK_OUT)
  await autoId(page, `ApproveTimePage-clock-${staffId}-times-save`).click()
  await expect(page.getByText('Clock times saved.').last()).toBeVisible()
}

test.use({ loginRole: 'officeStaff' })

test("a person's clocked time on no job is swept onto General work and the day approved", async ({
  authenticatedPage: page,
  browser,
  baseURL,
}, testInfo) => {
  const origin = z.string().parse(baseURL)
  const seeded = await seedAsSuperuser(browser, origin, FUTURE_WEEK)
  const waitingEntryId = await bookAsWorkshopUser(browser, origin, seeded)
  const staffId = seeded.staff.id
  const sweepButton = autoId(page, `ApproveTimePage-sweep-${staffId}`)
  const state = autoId(page, `ApproveTimePage-state-${staffId}`)
  let unallocated = 0

  await test.step('the office sets the clock times, and the rest shows as not on a job', async () => {
    await page.goto(`/timesheets/approve?date=${seeded.date}`)
    await setClock(page, staffId)
    unallocated = await expectedSweep(page, seeded.date, staffId)
    await expect(sweepButton).toHaveText(`Sweep ${formatHoursDisplay(unallocated)} to General work`)
  })

  // docs/design-language.md: the row now carries a second action, so it is
  // looked at on a desktop, a tablet and a phone. The page never scrolls
  // sideways, and the sweep stays reachable.
  for (const width of [1366, 1024, 390]) {
    await test.step(`holds at ${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 })
      await sweepButton.scrollIntoViewIfNeeded()
      await expect(sweepButton).toBeInViewport({ ratio: 1 })
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow, `the page must not scroll sideways at ${width}px`).toBeLessThanOrEqual(0)
      await testInfo.attach(`general-work-sweep-${width}`, {
        body: await page.screenshot({ animations: 'disabled', fullPage: true }),
        contentType: 'image/png',
      })
    })
  }
  await page.setViewportSize({ width: 1366, height: 900 })

  await test.step('sweeping puts exactly that on General work and approves the day', async () => {
    await sweepButton.click()
    await expect(
      page.getByText(`${formatHoursDisplay(unallocated)} put on General work.`),
    ).toBeVisible()
    await expect(state).toContainText('Approved')
    await expect(sweepButton).toHaveCount(0)
    const entries = autoId(page, `ApproveTimePage-entries-${staffId}`)
    const swept = entries.locator('li', { hasText: 'General work' })
    await expect(swept).toHaveCount(1)
    await expect(swept).toContainText(formatHoursDisplay(unallocated))
    // Sweeping is approving: the worker's own waiting entry went with the day.
    await expect(autoId(page, `ApproveTimePage-entry-${waitingEntryId}`)).toContainText('Approved')
  })
})

test('sweeping everyone on a day sweeps a person the office clocked', async ({
  authenticatedPage: page,
}) => {
  // A weekday the week after FUTURE_WEEK, so the two tests share no day.
  const day = shiftDate(FUTURE_WEEK, 8)
  const body = approvals.parse(
    await (await page.request.get(`/api/timesheets/approvals/?date=${day}`)).json(),
  )
  // Someone not yet clocked on the day, so the times set here are the day's.
  const staffId = body.staff.find((each) => each.clock.state === 'not_clocked_in')?.staff_id
  if (staffId === undefined) throw new Error(`Everyone on ${day} is already clocked.`)
  const state = autoId(page, `ApproveTimePage-state-${staffId}`)

  await page.goto(`/timesheets/approve?date=${day}`)
  await setClock(page, staffId)
  const hours = await expectedSweep(page, day, staffId)
  await expect(autoId(page, `ApproveTimePage-sweep-${staffId}`)).toHaveText(
    `Sweep ${formatHoursDisplay(hours)} to General work`,
  )

  await autoId(page, 'ApproveTimePage-sweep-day').click()

  await expect(page.getByText('put on General work.')).toBeVisible()
  await expect(state).toContainText('Approved')
  const swept = autoId(page, `ApproveTimePage-entries-${staffId}`).locator('li', {
    hasText: 'General work',
  })
  await expect(swept).toContainText(formatHoursDisplay(hours))
})
