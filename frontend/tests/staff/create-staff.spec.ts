import { test, expect } from '../fixtures/auth'
import { autoId, dismissToasts } from '../fixtures/helpers'

test.describe('create staff', () => {
  test('can create a new staff member', async ({ authenticatedPage: page }) => {
    const timestamp = Date.now()
    const testEmail = `e2e.test.${timestamp}@example.com`
    const testPassword = 'TestPassword123!'

    await test.step('navigate to staff management page', async () => {
      await page.goto('/admin/staff')
      await page.waitForLoadState('networkidle')
    })

    await test.step('open new staff modal', async () => {
      await autoId(page, 'AdminStaffView-new-staff').click()
      // Wait for dialog to appear (DialogContent has data-slot="dialog-content")
      await page.locator('[data-slot="dialog-content"]').waitFor({ timeout: 10000 })
      await expect(page.getByRole('heading', { name: 'New Staff' })).toBeVisible()
    })

    await test.step('fill in staff details', async () => {
      await autoId(page, 'StaffFormModal-first-name').fill('E2E Test')
      await autoId(page, 'StaffFormModal-last-name').fill(`User ${timestamp}`)
      await autoId(page, 'StaffFormModal-email').fill(testEmail)
      await autoId(page, 'StaffFormModal-password').fill(testPassword)
      await autoId(page, 'StaffFormModal-password-confirm').fill(testPassword)
    })

    await test.step('submit form and verify success', async () => {
      await dismissToasts(page)

      // Wait for API response
      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().includes('/accounts/api/staff') &&
          response.request().method() === 'POST' &&
          response.status() === 201,
        { timeout: 15000 },
      )

      await autoId(page, 'StaffFormModal-submit').click()
      await responsePromise

      // Modal should close
      await page.locator('[data-slot="dialog-content"]').waitFor({
        state: 'hidden',
        timeout: 10000,
      })

      // Success toast should appear
      await expect(page.locator('[data-sonner-toast]')).toContainText('successfully', {
        timeout: 5000,
      })

      console.log(`Successfully created staff member: E2E Test User ${timestamp}`)
    })
  })
})
