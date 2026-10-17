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
  WORKER_HOURS,
  bookAsWorkshopUser,
  getLatestWeekdayDate,
  seedLabourForWeek,
  type SeededLabour,
} from './support'

/**
 * 06:30 to 15:00 with the standard breaks the office's times put on the day:
 * 8h 30m here, less the 30m unpaid lunch and the two 15m paid breaks, leaves
 * 7h 30m to be on jobs. With nothing entered, that is what a sweep moves.
 */
const CLOCK_IN = '06:30'
const CLOCK_OUT = '15:00'
const HOURS_FOR_JOBS = 7.5

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
  // The seeded hours and the worker's waiting entry are on a job; the rest is not.
  const unallocated = Math.round((HOURS_FOR_JOBS - seeded.hours - WORKER_HOURS) * 100) / 100
  const sweepButton = autoId(page, `ApproveTimePage-sweep-${staffId}`)
  const state = autoId(page, `ApproveTimePage-state-${staffId}`)

  await test.step('the office sets the clock times, and the rest shows as not on a job', async () => {
    await page.goto(`/timesheets/approve?date=${seeded.date}`)
    await setClock(page, staffId)
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
  await expect(swept).toContainText(formatHoursDisplay(HOURS_FOR_JOBS))
})
