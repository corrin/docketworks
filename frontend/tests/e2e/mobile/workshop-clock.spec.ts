/**
 * Clocking in and out on a phone (KAN-376). A workshop user lands on My
 * time, where one card says where the day stands. A tap clocks today at the
 * server's time; a past day's times are set by hand, which is how this spec
 * states times without touching any clock.
 *
 * Each phone project works on its own past weekday, clear of the days the
 * My time spec books on. Today is one date for both projects in one
 * database, so the live taps run on one of them only.
 */
import type { Page, TestInfo } from '@playwright/test'

import { shiftDate } from '../../../src/lib/dates'
import { localIsoDate } from '../../../src/lib/format'
import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'
import { getLatestWeekdayDate } from '../timesheet/support'

/** iOS Safari zooms the page when a focused input's text is smaller than this. */
const IOS_NO_ZOOM_FONT_PX = 16
const PROJECT_WEEKS_BACK: Record<string, number> = { android: 2, iphone: 3 }
const LIVE_TAP_PROJECT = 'android'

function pastWeekday(projectName: string): string {
  const weeksBack = PROJECT_WEEKS_BACK[projectName]
  if (weeksBack === undefined) throw new Error(`No clock day for project "${projectName}"`)
  return shiftDate(getLatestWeekdayDate(), -7 * weeksBack)
}

async function openDay(page: Page, date: string): Promise<void> {
  // Signing in ends with the app's own move to My time. Let that land first:
  // on WebKit a goto issued while it was still in flight was cut across by it.
  await expect(autoId(page, 'DayCard')).toBeVisible()
  await page.goto(`/timesheets/my-time?date=${date}`)
  await expect(autoId(page, 'DayCard')).toBeVisible()
}

async function setTimes(page: Page, start: string, finish: string): Promise<void> {
  await autoId(page, 'DayCard-change-times').tap()
  await autoId(page, 'DayCard-start').fill(start)
  await autoId(page, 'DayCard-finish').fill(finish)
  await autoId(page, 'DayCard-times-save').tap()
}

async function attachScreenshot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await testInfo.attach(name, {
    body: await page.screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  })
}

test.use({ loginRole: 'workshop' })

test.describe('workshop clocking on a phone', () => {
  test("a past day's times are set by hand, refused past midnight, and reopened", async ({
    authenticatedPage: page,
  }, testInfo) => {
    const day = pastWeekday(testInfo.project.name)
    const state = autoId(page, 'DayCard-state')

    await test.step('signing in lands on My time', async () => {
      await expect(page).toHaveURL(/\/timesheets\/my-time/)
    })

    await test.step('a past day offers its times, not a clock tap', async () => {
      await openDay(page, day)
      await expect(state).toHaveText('Not clocked in')
      await expect(autoId(page, 'DayCard-clock-in')).toHaveCount(0)
      await attachScreenshot(page, testInfo, 'day-card-empty')
    })

    await test.step('started 06:30, finished 15:00', async () => {
      await autoId(page, 'DayCard-change-times').tap()
      for (const field of ['start', 'finish']) {
        const fontPx = await autoId(page, `DayCard-${field}`).evaluate((element) =>
          Number.parseFloat(getComputedStyle(element).fontSize),
        )
        expect(fontPx, `${field} font size`).toBeGreaterThanOrEqual(IOS_NO_ZOOM_FONT_PX)
      }
      await autoId(page, 'DayCard-start').fill('06:30')
      await autoId(page, 'DayCard-finish').fill('15:00')
      await autoId(page, 'DayCard-times-save').tap()
      await expect(page.getByText('Clock times saved.')).toBeVisible()
      // The server works out how long he was here; the card only prints it.
      await expect(state).toHaveText('Clocked out. 06:30 to 15:00, here 8h 30m')
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow, 'the page must not scroll sideways on a phone').toBeLessThanOrEqual(0)
      await attachScreenshot(page, testInfo, 'day-card-clocked-out')
    })

    await test.step('Clock back in reopens the day', async () => {
      await autoId(page, 'DayCard-clock-back-in').tap()
      await expect(state).toHaveText('At work since 06:30')
    })

    await test.step('another day names the day left open, and leads back to it', async () => {
      await page.goto(`/timesheets/my-time?date=${shiftDate(day, 1)}`)
      await expect(autoId(page, 'DayCard-pending')).toContainText('is still clocked in')
      await autoId(page, 'DayCard-pending-open').tap()
      await expect(page).toHaveURL(new RegExp(`date=${day}`))
      await expect(state).toHaveText('At work since 06:30')
    })

    await test.step('the finish is set, and the day is closed again', async () => {
      await setTimes(page, '06:30', '15:00')
      await expect(state).toHaveText('Clocked out. 06:30 to 15:00, here 8h 30m')
      await expect(autoId(page, 'DayCard-pending')).toHaveCount(0)
    })
  })

  test.describe('a finish past midnight', () => {
    // The 400 is the refusal this test is about.
    test.use({ expectedConsoleErrors: [/the server responded with a status of 400/] })

    test('is refused in words that send the worker to the office', async ({
      authenticatedPage: page,
    }, testInfo) => {
      const day = shiftDate(pastWeekday(testInfo.project.name), -1)
      await openDay(page, day)

      await setTimes(page, '16:00', '00:20')

      await expect(page.getByText('ask the office to put it right')).toBeVisible()
      await expect(autoId(page, 'DayCard-state')).toHaveText('Not clocked in')
    })
  })

  test('today is clocked in and out with a tap', async ({ authenticatedPage: page }, testInfo) => {
    test.skip(
      testInfo.project.name !== LIVE_TAP_PROJECT,
      'Today is one date for both phone projects in one database: a second run meets "already clocked in".',
    )
    const state = autoId(page, 'DayCard-state')
    await openDay(page, localIsoDate())
    await expect(state).toHaveText('Not clocked in')

    await autoId(page, 'DayCard-clock-in').tap()
    await expect(page.getByText('Clocked in.')).toBeVisible()
    await expect(state).toHaveText(/^At work since \d{2}:\d{2}$/)
    await expect(autoId(page, 'DayCard-clock-out')).toBeVisible()

    // A tap out in the same minute as the tap in is refused (the finish must
    // be later), so the start is moved to midnight by hand first. Only a run
    // in the first minute of the day could still meet that refusal.
    await autoId(page, 'DayCard-change-times').tap()
    await autoId(page, 'DayCard-start').fill('00:00')
    await autoId(page, 'DayCard-times-save').tap()
    await expect(state).toHaveText('At work since 00:00')

    await autoId(page, 'DayCard-clock-out').tap()
    await expect(page.getByText('Clocked out.', { exact: true })).toBeVisible()
    await expect(state).toHaveText(/^Clocked out\. 00:00 to \d{2}:\d{2}, here /)
    await expect(autoId(page, 'DayCard-clock-in')).toHaveCount(0)
  })
})
