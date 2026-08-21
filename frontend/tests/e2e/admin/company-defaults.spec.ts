import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * Company defaults is the schema-driven settings screen: sections come from
 * /api/company-defaults/schema/, fields save via a dirty-fields-only PATCH, and
 * the page saves the way every settings screen saves (Save/Cancel disabled until
 * dirty, toast on result, confirm before abandoning edits). Role gating (PATCH is
 * superuser-only) is proven in apps/core/tests/test_company_defaults_api.py, not
 * here — the E2E account is a superuser.
 */

const DEFAULTS_PATH = '/api/company-defaults/'
const THEME_FIELD_ID = 'CompanyDefaultsPage-xero-field-xero_sales_branding_theme_id'
/** BrandingThemeSelect's label for an id Xero no longer offers — never a save target. */
const UNAVAILABLE_THEME_PREFIX = 'Unavailable theme'

test.describe('company defaults', () => {
  test('sections render from the schema and an edit round-trips', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/admin/company-defaults/company')
    await autoId(page, 'CompanyDefaultsPage-root').waitFor({ timeout: 30000 })

    // Schema-driven: the section nav and a known field both come from the API.
    await expect(autoId(page, 'CompanyDefaultsPage-section-link-xero')).toBeVisible()
    const email = autoId(page, 'CompanyDefaultsPage-company-field-company_email')
    await expect(email).toBeVisible()
    // company_name is read-only by contract (COMPANY_DEFAULTS_READ_ONLY_FIELDS);
    // email is the writable probe. The generic widget renders read_only as the
    // input's `readonly`, so the field stays focusable and copyable — asserting
    // toBeDisabled() would pin the wrong widget contract.
    await expect(autoId(page, 'CompanyDefaultsPage-company-field-company_name')).toHaveAttribute(
      'readonly',
      '',
    )

    const save = autoId(page, 'CompanyDefaultsPage-save-button')
    const cancel = autoId(page, 'CompanyDefaultsPage-cancel-button')
    // Nothing changed yet, so neither action is offered.
    await expect(save).toBeDisabled()
    await expect(cancel).toBeDisabled()

    const original = await email.inputValue()
    const testValue = `test${Date.now()}@example.com`

    // Cancel restores the snapshot without a network call.
    await email.fill(testValue)
    await expect(save).toBeEnabled()
    await cancel.click()
    await expect(email).toHaveValue(original)
    await expect(save).toBeDisabled()

    // Save: only the dirty field goes on the wire (exclude_unset is the contract).
    await email.fill(testValue)
    const saved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === DEFAULTS_PATH &&
        response.request().method() === 'PATCH',
    )
    await save.click()
    const patch = await saved
    expect(patch.ok()).toBe(true)
    // exclude_unset is the contract: an untouched field must not appear at all.
    const patchBody: unknown = patch.request().postDataJSON()
    expect(patchBody).toEqual({ company_email: testValue })
    await expect(page.getByText('Company saved')).toBeVisible()
    // Save going back to disabled is the proof the snapshot advanced from the
    // response, rather than the page merely having sent something.
    await expect(save).toBeDisabled()

    // The value came from the server, not from React state.
    await page.reload()
    await autoId(page, 'CompanyDefaultsPage-root').waitFor({ timeout: 30000 })
    await expect(autoId(page, 'CompanyDefaultsPage-company-field-company_email')).toHaveValue(
      testValue,
    )

    // Unsaved-changes guard: dismiss keeps you here, accept lets you leave.
    // Finances is the destination rather than Xero because every widget in it
    // is a plain number input — landing on Xero would mount BrandingThemeSelect
    // and make this test fail whenever the tenant connection is down, which is
    // the branding-theme test's business, not this one's.
    await email.fill('dirty@example.com')
    page.once('dialog', (dialog) => dialog.dismiss())
    await autoId(page, 'CompanyDefaultsPage-section-link-finances').click()
    await expect(page).toHaveURL(/\/admin\/company-defaults\/company$/)
    await expect(email).toHaveValue('dirty@example.com')

    page.once('dialog', (dialog) => dialog.accept())
    await autoId(page, 'CompanyDefaultsPage-section-link-finances').click()
    await expect(page).toHaveURL(/\/admin\/company-defaults\/finances$/)

    // Restore, so the spec is idempotent against the restored E2E database.
    await page.goto('/admin/company-defaults/company')
    await autoId(page, 'CompanyDefaultsPage-root').waitFor({ timeout: 30000 })
    const restored = autoId(page, 'CompanyDefaultsPage-company-field-company_email')
    await restored.fill(original)
    const restoreSaved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === DEFAULTS_PATH &&
        response.request().method() === 'PATCH',
    )
    await autoId(page, 'CompanyDefaultsPage-save-button').click()
    expect((await restoreSaved).ok()).toBe(true)
    await expect(restored).toHaveValue(original)
  })

  test('Xero branding theme saves, survives reload, and restores', async ({
    authenticatedPage: page,
  }) => {
    // Touches the live Xero tenant. The picker resolves to one of four states;
    // this test fails loudly on error, skips on the two states that offer
    // nothing to exercise, and never writes a null theme back (BrandingThemeSelect's
    // ported v1 rule: an empty selection means Xero setup is incomplete).
    await page.goto('/admin/company-defaults/xero')
    await autoId(page, 'CompanyDefaultsPage-root').waitFor({ timeout: 30000 })
    const selector = autoId(page, THEME_FIELD_ID)
    const emptyMarker = autoId(page, `${THEME_FIELD_ID}-empty`)
    const errorMarker = autoId(page, `${THEME_FIELD_ID}-error`)
    await expect(selector).toBeVisible({ timeout: 15000 })
    await expect
      .poll(
        async () => {
          if (await errorMarker.isVisible()) return 'error'
          if (await emptyMarker.isVisible()) return 'empty'
          const optionCount = await selector.locator('option:not([disabled])').count()
          return (await selector.isEnabled()) && optionCount > 0 ? 'ready' : 'loading'
        },
        { timeout: 15000, message: 'Xero branding themes never finished loading' },
      )
      .not.toBe('loading')
    // A broken Xero connection is a real defect, not a reason to skip.
    await expect(errorMarker).toBeHidden()
    test.skip(await emptyMarker.isVisible(), 'The connected Xero tenant has no branding themes')

    const originalValue = await selector.inputValue()
    // Read through HTMLOptionElement.value rather than the `value` attribute:
    // the property is the id the <select> would actually submit.
    const candidateIds = await selector
      .locator('option')
      .evaluateAll<string[], string, HTMLOptionElement>(
        (options, prefix) =>
          options
            .filter(
              (option) => option.value !== '' && !(option.textContent ?? '').startsWith(prefix),
            )
            .map((option) => option.value),
        UNAVAILABLE_THEME_PREFIX,
      )
    const testValue =
      originalValue === '' ? candidateIds[0] : candidateIds.find((id) => id !== originalValue)
    test.skip(testValue === undefined, 'No alternative branding theme to exercise')
    if (testValue === undefined) return

    const save = autoId(page, 'CompanyDefaultsPage-save-button')
    try {
      await selector.selectOption(testValue)
      await expect(save).toBeEnabled()
      await save.click()
      await expect(page.getByText('Xero saved')).toBeVisible()
      await expect(save).toBeDisabled({ timeout: 10000 })

      await page.reload()
      await expect(selector).toBeVisible({ timeout: 15000 })
      await expect(selector).toHaveValue(testValue)
    } finally {
      // An originally-null theme means Xero setup was incomplete; restoring it
      // would deliberately write the null the widget exists to prevent.
      if (originalValue !== '') {
        // Only reached dirty when an assertion above already failed, and a dirty
        // page answers the browser's beforeunload prompt instead of navigating.
        page.once('dialog', (dialog) => dialog.accept())
        await page.goto('/admin/company-defaults/xero')
        await expect(selector.locator(`option[value="${originalValue}"]`)).toBeAttached({
          timeout: 15000,
        })
        if ((await selector.inputValue()) !== originalValue) {
          await selector.selectOption(originalValue)
          await save.click()
          await expect(save).toBeDisabled({ timeout: 10000 })
        }
      }
    }
  })
})
