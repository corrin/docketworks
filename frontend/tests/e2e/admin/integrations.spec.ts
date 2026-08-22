import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * Integrations is the install's vendor-credential screen (ADR 0053): one row,
 * one section per integration, secrets reported as configured/not configured
 * and never echoed. It saves the way every settings screen saves (Save/Cancel
 * disabled until dirty, dirty-fields-only PATCH, toast on result). Role gating
 * (both verbs are superuser-only) is proven in
 * apps/core/tests/test_integration_settings_api.py — the E2E account is a
 * superuser.
 */

const SETTINGS_PATH = '/api/integration-settings/'
const ACCOUNT_CODE_ID = 'IntegrationsPage-phone-field-phone_provider_account_code'

test.describe('integrations', () => {
  test('secrets report presence only, and a plain edit round-trips', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/admin/integrations')
    await autoId(page, 'IntegrationsPage-root').waitFor({ timeout: 30000 })

    // The dev database holds the Maps key (the pickup-address spec depends on
    // it); the screen says so without ever putting the value in the DOM.
    const mapsStatus = autoId(page, 'IntegrationsPage-google-status-google_maps_api_key')
    await expect(mapsStatus).toHaveText('Configured')
    await expect(autoId(page, 'IntegrationsPage-google-field-google_maps_api_key')).toHaveValue('')

    const save = autoId(page, 'IntegrationsPage-save-button')
    const cancel = autoId(page, 'IntegrationsPage-cancel-button')
    await expect(save).toBeDisabled()
    await expect(cancel).toBeDisabled()

    const accountCode = autoId(page, ACCOUNT_CODE_ID)
    const original = await accountCode.inputValue()
    const testValue = `e2e-${Date.now()}`

    // Cancel restores the snapshot without a network call.
    await accountCode.fill(testValue)
    await expect(save).toBeEnabled()
    await cancel.click()
    await expect(accountCode).toHaveValue(original)
    await expect(save).toBeDisabled()

    try {
      await accountCode.fill(testValue)
      const saved = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === SETTINGS_PATH &&
          response.request().method() === 'PATCH',
      )
      await save.click()
      const patch = await saved
      expect(patch.ok()).toBe(true)
      // exclude_unset is the contract: nothing but the edited field goes on the wire.
      const patchBody: unknown = patch.request().postDataJSON()
      expect(patchBody).toEqual({ phone_provider_account_code: testValue })
      await expect(page.getByText('Integrations saved')).toBeVisible()
      // Label plus disabled: `disabled` alone is also true mid-flight.
      await expect(save).toHaveText('Save')
      await expect(save).toBeDisabled()

      await page.reload()
      await autoId(page, 'IntegrationsPage-root').waitFor({ timeout: 30000 })
      await expect(autoId(page, ACCOUNT_CODE_ID)).toHaveValue(testValue)
    } finally {
      // Restore, so the spec is idempotent against the E2E database. An
      // emptied box is sent as null (ADR 0040), which is what "unset" was.
      page.once('dialog', (dialog) => dialog.accept())
      await page.goto('/admin/integrations')
      await autoId(page, 'IntegrationsPage-root').waitFor({ timeout: 30000 })
      const restored = autoId(page, ACCOUNT_CODE_ID)
      await restored.fill(original)
      const restoreSaved = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === SETTINGS_PATH &&
          response.request().method() === 'PATCH',
      )
      await autoId(page, 'IntegrationsPage-save-button').click()
      expect((await restoreSaved).ok()).toBe(true)
      await expect(restored).toHaveValue(original)
    }
  })
})
