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
 * 06:30 to 15:00 with the standard breaks the office's times put on the day
 * (paid 08:30 to 08:45, lunch 11:30 to 12:00, paid 13:30 to 13:45). With
 * nothing entered, the sweep fills each stretch between them: 7h 30m in four.
 */
const CLOCK_IN = '06:30'
const CLOCK_OUT = '15:00'
const HOURS_FOR_JOBS = 7.5
const STRETCHES = [
  ['06:30 to 08:30', 2],
  ['08:45 to 11:30', 2.75],
  ['12:00 to 13:30', 1.5],
  ['13:45 to 15:00', 1.25],
] as const

/** Five weeks ahead: a week no other timesheet spec books or clocks on. */
const FUTURE_WEEK = shiftDate(mondayOf(getLatestWeekdayDate()), 35)

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

  await test.step('the office sets the clock times, and the rest shows as not on a job', async () => {
    await page.goto(`/timesheets/approve?date=${seeded.date}`)
    await setClock(page, staffId)
    await expect(sweepButton).toContainText('to General work')
  })

  // docs/design-language.md: the row now carries a second action, so it is
  // looked at on a desktop, a tablet and a phone. The page never scrolls
  // sideways; on a phone the table scrolls in its own container, and the
  // sweep below is done at phone width, which proves it reachable there.
  for (const width of [1366, 1024, 390]) {
    await test.step(`holds at ${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 })
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

  // Where each stretch falls around the worker's entries is the unit tests'
  // to prove (test_approval TestSweep); here, the sweep on a phone.
  await test.step('swept on a phone: the day goes on General work and is approved', async () => {
    await sweepButton.click()
    await expect(page.getByText('put on General work.')).toBeVisible()
    await expect(state).toContainText('Approved')
    await expect(sweepButton).toHaveCount(0)
    const entries = autoId(page, `ApproveTimePage-entries-${staffId}`)
    await expect(entries.locator('li', { hasText: 'General work' }).first()).toBeVisible()
    // Sweeping is approving: the worker's own waiting entry went with the day.
    await expect(autoId(page, `ApproveTimePage-entry-${waitingEntryId}`)).toContainText('Approved')
  })
})

test('sweeping everyone on a day sweeps a person the office clocked', async ({
  authenticatedPage: page,
}) => {
  // A weekday the week after FUTURE_WEEK, so the two tests share no day.
  const day = shiftDate(FUTURE_WEEK, 8)
  const listed = z
    .object({ staff: z.array(z.object({ staff_id: z.string() })) })
    .parse(await (await page.request.get(`/api/timesheets/approvals/?date=${day}`)).json())
  const staffId = listed.staff[0]?.staff_id
  if (staffId === undefined) throw new Error(`Nobody is on the timesheet for ${day}.`)
  const state = autoId(page, `ApproveTimePage-state-${staffId}`)

  await page.goto(`/timesheets/approve?date=${day}`)
  await setClock(page, staffId)
  await expect(autoId(page, `ApproveTimePage-sweep-${staffId}`)).toHaveText(
    `Sweep ${formatHoursDisplay(HOURS_FOR_JOBS)} to General work`,
  )

  await autoId(page, 'ApproveTimePage-sweep-day').click()

  await expect(
    page.getByText(`${formatHoursDisplay(HOURS_FOR_JOBS)} put on General work.`),
  ).toBeVisible()
  await expect(state).toContainText('Approved')
  const swept = autoId(page, `ApproveTimePage-entries-${staffId}`).locator('li', {
    hasText: 'General work',
  })
  await expect(swept).toHaveCount(STRETCHES.length)
  for (const [index, [times, hours]] of STRETCHES.entries()) {
    await expect(swept.nth(index)).toContainText(times)
    await expect(swept.nth(index)).toContainText(formatHoursDisplay(hours))
  }
})
