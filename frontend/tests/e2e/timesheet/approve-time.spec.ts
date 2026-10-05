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

import { mondayOf } from '../../../src/lib/dates'
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
