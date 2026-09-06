/**
 * The staff admin list splits Current from Past, defaulting to Current.
 *
 * Serial by design, and it creates its own subject rather than reaching for a
 * departed row the restored database may or may not hold: the property under
 * test is that offboarding MOVES someone between the tabs, which needs both
 * states of one person. The [TEST] row is left behind for the database restore
 * to sweep — there is no staff DELETE, offboarding is date_left.
 */
import { z } from 'zod'

import { expect, test } from '../fixtures/auth'
import { autoId, dismissToasts } from '../helpers'

const timestamp = Date.now()
const firstName = '[TEST] Tabs'
const lastName = `Leaver ${timestamp}`
const email = `e2e.tabs.${timestamp}@example.com`

let staffId: string | undefined

function requireStaffId(): string {
  if (!staffId) throw new Error('The create test did not run or did not capture the staff id.')
  return staffId
}

test.describe.serial('staff Current/Past tabs', () => {
  test('a newly created staff member appears under Current', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/admin/staff')
    await autoId(page, 'StaffAdminPage-new-staff').click()
    await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()

    await autoId(page, 'StaffFormDialog-first-name').fill(firstName)
    await autoId(page, 'StaffFormDialog-last-name').fill(lastName)
    await autoId(page, 'StaffFormDialog-email').fill(email)
    await autoId(page, 'StaffFormDialog-password').fill('TestPassword123!')
    await autoId(page, 'StaffFormDialog-password-confirm').fill('TestPassword123!')
    await autoId(page, 'StaffFormDialog-base-wage-rate').fill('30')
    await dismissToasts(page)

    const created = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/accounts/staff/' &&
        response.request().method() === 'POST',
    )
    await autoId(page, 'StaffFormDialog-submit').click()
    const response = await created
    expect(response.status(), `create failed: ${await response.text()}`).toBe(201)
    staffId = z.object({ id: z.string() }).parse(await response.json()).id

    // Current is the default tab: a regression defaulting to Past, or showing
    // everyone, would hide the staff an office manager actually works with.
    await expect(autoId(page, 'StaffAdminPage-tab-current')).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await expect(autoId(page, `StaffAdminPage-row-${requireStaffId()}`)).toBeVisible()
  })

  test('the quick filter narrows the list to the matching staff member', async ({
    authenticatedPage: page,
  }) => {
    const id = requireStaffId()
    await page.goto('/admin/staff')
    await expect(autoId(page, `StaffAdminPage-row-${id}`)).toBeVisible()

    // Assert the mechanism, not a row count: production holds 27 staff and this
    // database holds a different number, so "one row remains" would be an
    // assertion about the corpus (ADR 0054).
    await autoId(page, 'StaffAdminPage-search').fill(lastName)
    await expect(autoId(page, `StaffAdminPage-row-${id}`)).toBeVisible()
    await expect(page.locator('[data-automation-id^="StaffAdminPage-row-"]')).toHaveCount(1)

    await autoId(page, 'StaffAdminPage-search').fill(`no such staff ${timestamp}`)
    await expect(page.locator('[data-automation-id^="StaffAdminPage-row-"]')).toHaveCount(0)
  })

  test('offboarding moves the staff member from Current to Past', async ({
    authenticatedPage: page,
  }) => {
    const id = requireStaffId()
    await page.goto('/admin/staff')
    await autoId(page, `StaffAdminPage-edit-staff-${id}`).click()
    await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()

    await autoId(page, 'StaffFormDialog-date-left').fill('2025-01-31')
    const patched = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/accounts/staff/${id}/` &&
        response.request().method() === 'PATCH',
    )
    await autoId(page, 'StaffFormDialog-submit').click()
    const response = await patched
    expect(response.status(), `offboarding failed: ${await response.text()}`).toBe(200)
    await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()

    // The whole point of the split: a departed member leaves Current entirely
    // rather than staying in the list with a status caption.
    await expect(autoId(page, `StaffAdminPage-row-${id}`)).toBeHidden()

    await autoId(page, 'StaffAdminPage-tab-past').click()
    const pastRow = autoId(page, `StaffAdminPage-row-${id}`)
    await expect(pastRow).toBeVisible()
    await expect(pastRow).toContainText('Left')
  })
})
