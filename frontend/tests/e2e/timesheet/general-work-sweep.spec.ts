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
import { getPostableWeek, getWorkshopStaff } from '../fixtures/api'
import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'
import { asSuperuser, bookAsWorkshopUser, getLatestWeekdayDate, seedLabourForWeek } from './support'

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

/**
 * Five weeks before both this week and the postable week: a week no other
 * timesheet or payroll spec books, clocks or posts on. Not ahead: the server
 * refuses to sweep a day that has not happened.
 */
async function sweepWeek(browser: Browser, origin: string): Promise<string> {
  const postable = await asSuperuser(browser, origin, getPostableWeek)
  const thisWeek = mondayOf(getLatestWeekdayDate())
  return shiftDate(postable < thisWeek ? postable : thisWeek, -35)
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
  const week = await sweepWeek(browser, origin)
  const seeded = await asSuperuser(browser, origin, (setup) => seedLabourForWeek(setup, week))
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
    await expect(page.getByText('booked to General work.')).toBeVisible()
    await expect(state).toContainText('Approved')
    // ADR 0067: the button stays, disabled, and says why.
    await expect(sweepButton).toBeDisabled()
    await expect(sweepButton).toHaveText('All time is on jobs')
    const entries = autoId(page, `ApproveTimePage-entries-${staffId}`)
    await expect(entries.locator('li', { hasText: 'General work' }).first()).toBeVisible()
    // Sweeping is approving: the worker's own waiting entry went with the day.
    await expect(autoId(page, `ApproveTimePage-entry-${waitingEntryId}`)).toContainText('Approved')
  })
})

test('sweeping everyone on a day sweeps a person the office clocked', async ({
  authenticatedPage: page,
  browser,
  baseURL,
}) => {
  const origin = z.string().parse(baseURL)
  // A weekday the week after the first test's, so the two share no day.
  const day = shiftDate(await sweepWeek(browser, origin), 8)
  const staffId = (await asSuperuser(browser, origin, getWorkshopStaff)).id
  const state = autoId(page, `ApproveTimePage-state-${staffId}`)

  await page.goto(`/timesheets/approve?date=${day}`)
  await setClock(page, staffId)
  await expect(autoId(page, `ApproveTimePage-sweep-${staffId}`)).toHaveText(
    `Book ${formatHoursDisplay(HOURS_FOR_JOBS)} to General work`,
  )

  await autoId(page, 'ApproveTimePage-sweep-day').click()

  await expect(
    page.getByText(`${formatHoursDisplay(HOURS_FOR_JOBS)} booked to General work.`),
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
