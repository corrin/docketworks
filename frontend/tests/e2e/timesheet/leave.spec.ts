import type { Page } from '@playwright/test'

import { getJobLabourRates, getWorkshopStaff, seedTimesheetLabour } from '../fixtures/api'
import { test, expect } from '../fixtures/auth'
import { mondayOf, shiftDate } from '../../../src/lib/dates'
import { formatDate, localIsoDate } from '../../../src/lib/format'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'

/** The Monday strictly after today, via the app's own week arithmetic. */
function nextMonday(): string {
  return mondayOf(shiftDate(localIsoDate(), 7))
}

async function openLeave(page: Page): Promise<void> {
  await page.goto('/timesheets/leave')
  await autoId(page, 'LeavePage-root').waitFor({ timeout: 30000 })
}

test.describe('leave management', () => {
  test('the Timesheets and Admin menus expose their first leave entries', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/kanban')

    await autoId(page, 'AppNavbar-timesheets-menu').click()
    await expect(autoId(page, 'AppNavbar-leave')).toBeVisible()
    await autoId(page, 'AppNavbar-leave').click()
    await expect(autoId(page, 'LeavePage-root')).toBeVisible()

    await autoId(page, 'AppNavbar-admin-menu').click()
    await autoId(page, 'AppNavbar-leave-settings').click()
    await expect(autoId(page, 'LeaveSettingsPage-root')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Leave settings' })).toBeVisible()
  })

  test('an admin creates upcoming leave employee-first, then cancels it', async ({
    authenticatedPage: page,
  }) => {
    const workshop = await getWorkshopStaff(page)
    await openLeave(page)
    await autoId(page, 'LeavePage-new').click()

    const employee = page.getByLabel('Employee')
    const leaveType = page.getByLabel('Leave type')
    await expect(leaveType).toBeDisabled()
    await employee.selectOption(workshop.id)
    const employeeName = await employee.locator('option:checked').textContent()
    await expect(leaveType).toBeEnabled()
    await leaveType.selectOption({ index: 1 })
    const leaveTypeName = await leaveType.locator('option:checked').textContent()

    const date = nextMonday()
    await page.getByLabel('Start date').fill(date)
    await page.getByLabel('End date').fill(date)
    await page.getByLabel('Note (optional)').fill('[TEST] Leave E2E')
    await page.getByRole('button', { name: 'Preview scheduled days' }).click()
    // Whole days (owner, 2026-10-25): the day is listed with the hours it
    // takes, and nobody types hours.
    await expect(autoId(page, `LeaveRequestDialog-hours-${date}`)).toBeVisible({
      timeout: 30000,
    })
    await expect(page.getByLabel(`Hours for ${date}`)).toHaveCount(0)

    const createResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/timesheets/leave/requests/' &&
        response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: 'Save leave' }).click()
    expect((await createResponse).ok()).toBe(true)

    const row = page
      .getByRole('row')
      .filter({ hasText: employeeName ?? '' })
      .filter({
        hasText: leaveTypeName ?? '',
      })
    await expect(row).toBeVisible()
    page.once('dialog', (dialog) => dialog.accept())
    const deleteResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/timesheets/leave/requests/') &&
        response.request().method() === 'DELETE',
    )
    await row.getByRole('button', { name: 'Cancel' }).click()
    expect((await deleteResponse).status()).toBe(204)
    await expect(row).toHaveCount(0)
  })

  test('leave on a day that already has time fills the rest and tells the office', async ({
    authenticatedPage: page,
  }) => {
    const workshop = await getWorkshopStaff(page)
    // The Tuesday after next: a day the first leave test does not book.
    const date = shiftDate(nextMonday(), 8)
    const jobId = getJobIdFromUrl(await createTestJob(page, 'Leave fill'))
    const [rate] = await getJobLabourRates(page, jobId)
    if (rate === undefined) throw new Error(`Job ${jobId} has no labour rates.`)
    await seedTimesheetLabour(page, {
      jobId,
      staffId: workshop.id,
      labourSubtype: rate.labour_subtype,
      date,
      hours: 2,
      description: '[TEST] time before the leave',
    })

    await openLeave(page)
    await autoId(page, 'LeavePage-new').click()
    const employee = page.getByLabel('Employee')
    await employee.selectOption(workshop.id)
    const employeeName = (await employee.locator('option:checked').textContent()) ?? ''
    await page.getByLabel('Leave type').selectOption({ index: 1 })
    await page.getByLabel('Start date').fill(date)
    await page.getByLabel('End date').fill(date)
    await page.getByLabel('Note (optional)').fill('[TEST] Leave fills the day')
    await page.getByRole('button', { name: 'Preview scheduled days' }).click()
    await expect(autoId(page, `LeaveRequestDialog-hours-${date}`)).toBeVisible({
      timeout: 30000,
    })
    await page.getByRole('button', { name: 'Save leave' }).click()

    await expect(
      page.getByText(
        new RegExp(`on ${date}, but the day already had time entered: .+ put to leave\\.`),
      ),
    ).toBeVisible()

    const row = page
      .getByRole('row')
      .filter({ hasText: employeeName })
      .filter({ hasText: formatDate(date) })
    page.once('dialog', (dialog) => dialog.accept())
    await row.getByRole('button', { name: 'Cancel' }).click()
    await expect(row).toHaveCount(0)
  })
})
