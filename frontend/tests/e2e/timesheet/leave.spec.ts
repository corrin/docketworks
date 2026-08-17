import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

function nextMonday(): string {
  const target = new Date()
  const daysUntilMonday = (8 - target.getDay()) % 7 || 7
  target.setDate(target.getDate() + daysUntilMonday)
  const month = String(target.getMonth() + 1).padStart(2, '0')
  const day = String(target.getDate()).padStart(2, '0')
  return `${target.getFullYear()}-${month}-${day}`
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
    await openLeave(page)
    await autoId(page, 'LeavePage-new').click()

    const employee = page.getByLabel('Employee')
    const leaveType = page.getByLabel('Leave type')
    await expect(leaveType).toBeDisabled()
    await employee.selectOption({ index: 1 })
    const employeeName = await employee.locator('option:checked').textContent()
    await expect(leaveType).toBeEnabled()
    await leaveType.selectOption({ index: 1 })
    const leaveTypeName = await leaveType.locator('option:checked').textContent()

    const date = nextMonday()
    await page.getByLabel('Start date').fill(date)
    await page.getByLabel('End date').fill(date)
    await page.getByLabel('Note (optional)').fill('[TEST] Leave E2E')
    await page.getByRole('button', { name: 'Preview scheduled days' }).click()
    await expect(page.getByLabel(`Hours for ${date}`)).toBeVisible({ timeout: 30000 })

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
})
