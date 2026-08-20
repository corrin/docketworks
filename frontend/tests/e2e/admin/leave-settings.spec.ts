import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * Leave settings saves the way every settings screen saves: one page-level
 * Cancel + Save, disabled until something actually changed, a toast on the
 * result, and a confirm before navigating away with unsaved edits.
 *
 * The spec renames a leave type and restores it. Deliberately NOT covered
 * here: rebinding the Job or the Xero pay item. Every other leave spec depends
 * on those mappings staying configured, and the display name exercises the
 * identical path — the same PATCH, the same transaction, the same snapshot
 * refresh. The transactional behaviour that a rename cannot show (a rejected
 * row rolling back its neighbours, two types swapping jobs) is proved against
 * the database in apps/timesheet/tests/test_leave_service.py, where it can be
 * asserted rather than inferred from a screen.
 */

const SETTINGS_PATH = '/api/timesheets/leave-settings/'
const CODE = 'annual_leave'

async function clickLeaveInTimesheetsMenu(page: Page): Promise<void> {
  await autoId(page, 'AppNavbar-timesheets-menu').click()
  const link = autoId(page, 'AppNavbar-leave')
  await expect(link).toBeVisible()
  await link.click()
}

test.describe('leave settings', () => {
  test('an admin renames a leave type and the save round-trips', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/admin/leave-settings')
    await autoId(page, 'LeaveSettingsPage-root').waitFor({ timeout: 30000 })

    const save = autoId(page, 'LeaveSettingsPage-save-button')
    const cancel = autoId(page, 'LeaveSettingsPage-cancel-button')
    const nameField = page.getByLabel(`${CODE} display name`)
    await nameField.waitFor({ timeout: 30000 })

    // Nothing changed yet, so neither action is offered.
    await expect(save).toBeDisabled()
    await expect(cancel).toBeDisabled()

    const original = await nameField.inputValue()
    const renamed = `${original} [TEST]`

    // Cancel discards without touching the server.
    await nameField.fill(renamed)
    await expect(save).toBeEnabled()
    await cancel.click()
    await expect(nameField).toHaveValue(original)
    await expect(save).toBeDisabled()

    // Save round-trips.
    await nameField.fill(renamed)
    const saved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === SETTINGS_PATH &&
        response.request().method() === 'PATCH',
    )
    await save.click()
    expect((await saved).ok()).toBe(true)
    await expect(page.getByText('Leave settings saved')).toBeVisible()
    // Save going back to disabled is the proof the snapshot advanced from the
    // response, rather than the page merely having sent something.
    await expect(save).toBeDisabled()

    // The value came from the server, not from React state.
    await page.reload()
    await autoId(page, 'LeaveSettingsPage-root').waitFor({ timeout: 30000 })
    await expect(page.getByLabel(`${CODE} display name`)).toHaveValue(renamed)

    // Leaving dirty prompts; refusing keeps the page.
    await page.getByLabel(`${CODE} display name`).fill(`${renamed} again`)
    page.once('dialog', (dialog) => dialog.dismiss())
    await clickLeaveInTimesheetsMenu(page)
    await expect(autoId(page, 'LeaveSettingsPage-root')).toBeVisible()

    // Accepting leaves. Reached by reloading first, because a refused
    // navigation leaves the nav menu needing two clicks to reopen (the KNOWN
    // GAP recorded on NavMenu) — asserting through that quirk would pin it as
    // intended behaviour rather than leave it visible as a defect.
    await page.reload()
    await autoId(page, 'LeaveSettingsPage-root').waitFor({ timeout: 30000 })
    await page.getByLabel(`${CODE} display name`).fill(`${renamed} again`)
    page.once('dialog', (dialog) => dialog.accept())
    await clickLeaveInTimesheetsMenu(page)
    await expect(autoId(page, 'LeavePage-root')).toBeVisible()

    // Restore, so the spec is idempotent against the restored E2E database.
    await page.goto('/admin/leave-settings')
    await autoId(page, 'LeaveSettingsPage-root').waitFor({ timeout: 30000 })
    const restored = page.getByLabel(`${CODE} display name`)
    await restored.waitFor({ timeout: 30000 })
    await restored.fill(original)
    const restoreSaved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === SETTINGS_PATH &&
        response.request().method() === 'PATCH',
    )
    await autoId(page, 'LeaveSettingsPage-save-button').click()
    expect((await restoreSaved).ok()).toBe(true)
    await expect(restored).toHaveValue(original)
  })

  test('the job picker offers only special jobs', async ({ authenticatedPage: page }) => {
    // The regression this review started from: the bare <select> this replaced
    // had no way to express — or fail to express — the special-only rule.
    await page.goto('/admin/leave-settings')
    await autoId(page, 'LeaveSettingsPage-root').waitFor({ timeout: 30000 })

    await autoId(page, `LeaveSettingsPage-job-${CODE}-trigger`).click()
    const list = autoId(page, `LeaveSettingsPage-job-${CODE}-list`)
    await list.waitFor({ timeout: 10000 })

    const options = list.locator(`[data-automation-id^="LeaveSettingsPage-job-${CODE}-option-"]`)
    await expect(options.first()).toBeVisible()
    for (const text of await options.allTextContents()) {
      expect(text).toContain('Special')
    }
  })
})
