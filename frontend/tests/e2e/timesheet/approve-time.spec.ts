/**
 * Approve time: the office's one screen for the day's timesheets (KAN-376).
 * Driven as an office user who is NOT a superuser, because any office staff
 * member approves time and the suite's other office login may do anything.
 *
 * The day is set up by the logins whose job that is, each in its own browser
 * context: the superuser seeds a job and picks a listed staff member (the
 * staff list is a superuser screen), and the workshop login books the entry
 * that waits.
 */
import type { Browser } from '@playwright/test'
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

const DRAWER = 'WorkshopTimesheetEntryDrawer'

async function seedAsSuperuser(browser: Browser, baseURL: string): Promise<SeededLabour> {
  const context = await browser.newContext({ baseURL })
  try {
    const page = await context.newPage()
    const { username, password } = e2eCredentials('office')
    await authenticateViaLoginPage(page, username, password, () => () => undefined)
    return await seedLabourForWeek(page, mondayOf(getLatestWeekdayDate()))
  } finally {
    await context.close()
  }
}

test.use({ loginRole: 'officeStaff' })

test('office staff correct a waiting entry and approve the day, and see no pay', async ({
  authenticatedPage: page,
  browser,
  baseURL,
}, testInfo) => {
  const origin = z.string().parse(baseURL)
  const seeded = await seedAsSuperuser(browser, origin)
  const waitingEntryId = await bookAsWorkshopUser(browser, origin, seeded)
  const staffId = seeded.staff.id
  const row = autoId(page, `ApproveTimePage-row-${staffId}`)
  const state = autoId(page, `ApproveTimePage-state-${staffId}`)
  const waiting = autoId(page, `ApproveTimePage-waiting-${staffId}`)

  await test.step('the navbar offers Approve time and not the superuser screens', async () => {
    await autoId(page, 'AppNavbar-timesheets-menu').click()
    await expect(autoId(page, 'AppNavbar-approve-time')).toBeVisible()
    await expect(autoId(page, 'AppNavbar-daily-timesheets')).toHaveCount(0)
    await autoId(page, 'AppNavbar-approve-time').click()
    await expect(page).toHaveURL(/\/timesheets\/approve\?date=\d{4}-\d{2}-\d{2}/)
  })

  await test.step('the person with time waiting is named, with hours and no pay', async () => {
    await page.goto(`/timesheets/approve?date=${seeded.date}`)
    await expect(row).toBeVisible()
    await expect(state).toContainText('Waiting for approval')
    await expect(waiting).toHaveText(formatHoursDisplay(WORKER_HOURS))
    await expect(autoId(page, 'ApproveTimePage-table')).not.toContainText('$')
    await testInfo.attach('approve-time-waiting', {
      body: await page.screenshot({ animations: 'disabled', fullPage: true }),
      contentType: 'image/png',
    })
  })

  await test.step('the waiting entry is corrected in the drawer and still waits', async () => {
    await autoId(page, `ApproveTimePage-open-${staffId}`).click()
    const entry = autoId(page, `ApproveTimePage-entry-${waitingEntryId}`)
    await expect(entry).toContainText('Waiting')
    await autoId(page, `ApproveTimePage-edit-${waitingEntryId}`).click()
    await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible()
    await autoId(page, `${DRAWER}-description`).fill('Corrected by the office')
    await autoId(page, `${DRAWER}-submit`).click()
    await expect(page.getByText('Time saved.')).toBeVisible()
    await expect(entry).toContainText('Corrected by the office')
    await expect(entry).toContainText('Waiting')
    await expect(waiting).toHaveText(formatHoursDisplay(WORKER_HOURS))
  })

  await test.step('one click approves the day', async () => {
    await autoId(page, `ApproveTimePage-approve-${staffId}`).click()
    await expect(page.getByText('day approved.')).toBeVisible()
    await expect(state).toContainText('Approved')
    await expect(waiting).toHaveText('0h')
    await expect(autoId(page, `ApproveTimePage-approve-${staffId}`)).toHaveCount(0)
    await expect(autoId(page, `ApproveTimePage-entry-${waitingEntryId}`)).toContainText('Approved')
  })
})

test("office staff correct a person's clock times, and the screen holds at three widths", async ({
  authenticatedPage: page,
}, testInfo) => {
  // A past weekday clear of the days the other specs clock and book on.
  const day = shiftDate(getLatestWeekdayDate(), -28)
  const listed = z
    .object({ staff: z.array(z.object({ staff_id: z.string() })) })
    .parse(await (await page.request.get(`/api/timesheets/approvals/?date=${day}`)).json())
  const staffId = listed.staff[0]?.staff_id
  if (staffId === undefined) throw new Error(`Nobody is on the timesheet for ${day}.`)
  const clock = autoId(page, `ApproveTimePage-clock-${staffId}`)
  const setClock = async (start: string, finish: string) => {
    await autoId(page, `ApproveTimePage-clock-edit-${staffId}`).click()
    await autoId(page, `ApproveTimePage-clock-${staffId}-start`).fill(start)
    await autoId(page, `ApproveTimePage-clock-${staffId}-finish`).fill(finish)
    await autoId(page, `ApproveTimePage-clock-${staffId}-times-save`).click()
    await expect(page.getByText('Clock times saved.').last()).toBeVisible()
  }

  await page.goto(`/timesheets/approve?date=${day}`)
  await expect(clock).toHaveText('Not clocked in')
  await autoId(page, `ApproveTimePage-open-${staffId}`).click()

  await test.step('the office sets the times a person did not clock', async () => {
    await setClock('06:30', '15:00')
    await expect(clock).toHaveText('Clocked out. 06:30 to 15:00, here 8h 30m')
    // Times the office itself set raise no warning: nobody is chased over
    // the office's own entry.
    await expect(autoId(page, `ApproveTimePage-row-${staffId}`)).not.toContainText('Did not clock')
  })

  await test.step("the day's breaks are listed, and one is corrected", async () => {
    const breaks = autoId(page, `ApproveTimePage-breaks-${staffId}`)
    await expect(breaks).toContainText('Paid break 08:30 to 08:45')
    await expect(breaks).toContainText('Unpaid break 11:30 to 12:00')
    await expect(breaks).toContainText('Paid break 13:30 to 13:45')

    await breaks.getByRole('button', { name: 'Unpaid break 11:30 to 12:00' }).click()
    await autoId(page, 'BreakSheet-start').fill('12:00')
    await autoId(page, 'BreakSheet-finish').fill('12:30')
    await autoId(page, 'BreakSheet-times-save').click()
    await expect(breaks).toContainText('Unpaid break 12:00 to 12:30')
  })

  await test.step('and corrects them', async () => {
    await setClock('06:30', '15:30')
    await expect(clock).toHaveText('Clocked out. 06:30 to 15:30, here 9h')
  })

  // docs/design-language.md: a new screen is looked at on a desktop, a tablet
  // and a phone. The table scrolls inside its own container; the page does not.
  for (const width of [1366, 1024, 390]) {
    await test.step(`holds at ${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 })
      // On a phone the clock words move under the name, so the state and the
      // row's action are in view without swiping the table.
      const clockWords =
        width < 640 ? autoId(page, `ApproveTimePage-clock-narrow-${staffId}`) : clock
      await expect(clockWords).toHaveText('Clocked out. 06:30 to 15:30, here 9h')
      await expect(autoId(page, `ApproveTimePage-state-${staffId}`)).toBeInViewport({ ratio: 1 })
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow, `the page must not scroll sideways at ${width}px`).toBeLessThanOrEqual(0)
      await page.screenshot({
        path: testInfo.outputPath(`approve-time-${width}.png`),
        animations: 'disabled',
        fullPage: true,
      })
    })
  }
})

test('approving the last person waiting turns the day to complete', async ({
  authenticatedPage: page,
  browser,
  baseURL,
}) => {
  const origin = z.string().parse(baseURL)
  const seeded = await seedAsSuperuser(browser, origin)
  // A Saturday: nobody is rostered, so the one person with time on it is the
  // only one expected, and approving them is the whole day.
  const saturday = shiftDate(mondayOf(getLatestWeekdayDate()), -2)
  await bookAsWorkshopUser(browser, origin, { ...seeded, date: saturday })
  const standing = autoId(page, 'ApproveTimePage-standing')

  await page.goto(`/timesheets/approve?date=${saturday}`)
  await expect(standing).toHaveText('0 of 1 approved')
  await expect(autoId(page, 'ApproveTimePage-table')).toContainText('Not rostered')

  await autoId(page, `ApproveTimePage-approve-${seeded.staff.id}`).click()

  await expect(standing).toHaveText('Day complete')
})
