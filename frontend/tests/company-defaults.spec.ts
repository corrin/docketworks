import { test, expect } from './fixtures/auth'
import { autoId } from './fixtures/helpers'

test('test can call backend API directly', async ({ authenticatedPage: page }) => {
  const response = await page.request.get('/api/company-defaults/', {
    headers: { Accept: 'application/json' },
  })

  console.log(`API response status: ${response.status()}`)

  // If we get HTML back, log it for debugging
  const contentType = response.headers()['content-type'] || ''
  if (!contentType.includes('application/json')) {
    const text = await response.text()
    console.log(`Unexpected content-type: ${contentType}`)
    console.log(`Response body (first 500 chars): ${text.substring(0, 500)}`)
  }

  expect(response.ok()).toBeTruthy()
  expect(contentType).toContain('application/json')

  const data = await response.json()
  expect(data.test_company_name).toBeDefined()
  expect(data.test_company_name).not.toBe('')

  console.log(`Test company name from API: ${data.test_company_name}`)
})

test('test company defaults edit and save', async ({ authenticatedPage: page }) => {
  // Navigate to the admin company index
  await page.goto('/admin/company')

  // Wait for the section buttons to load
  await page.waitForSelector('[data-automation-id="AdminCompanyView-company-button"]', {
    timeout: 15000,
  })

  // Click Company section — navigates to /admin/company/company
  await page.click('[data-automation-id="AdminCompanyView-company-button"]')

  await expect(page).toHaveURL(/\/admin\/company\/company$/)

  // Wait for the section form to render
  const form = page.locator('[data-automation-id="AdminCompanySectionView-form"]')
  await expect(form).toBeVisible({ timeout: 10000 })

  // Find the company email input (company_name is readonly)
  const companyEmailInput = page.locator(
    '[data-automation-id="SectionForm-company-field-company_email"]',
  )
  await expect(companyEmailInput).toBeVisible()

  // Get the original value
  const originalValue = await companyEmailInput.inputValue()
  console.log(`Original company email: ${originalValue}`)

  // Change to a test value with timestamp
  const testValue = `test${Date.now()}@example.com`
  await companyEmailInput.clear()
  await companyEmailInput.fill(testValue)
  await page.keyboard.press('Tab') // Blur to ensure v-model syncs
  await page.waitForTimeout(500) // Wait for Vue reactivity to propagate
  console.log(`Changed company email to: ${testValue}`)

  // Click the page-level Save button
  await page.click('[data-automation-id="AdminCompanySectionView-save-button"]')

  // Wait for save to complete (toast appears, snapshot reloads)
  await page.waitForTimeout(1500)

  // Navigate back to the index, then re-enter Company to verify persistence
  await page.click('[data-automation-id="AdminCompanySectionView-back-button"]')
  await expect(page).toHaveURL(/\/admin\/company$/)

  await page.click('[data-automation-id="AdminCompanyView-company-button"]')
  await expect(page).toHaveURL(/\/admin\/company\/company$/)
  await expect(form).toBeVisible({ timeout: 10000 })

  const savedInput = page.locator('[data-automation-id="SectionForm-company-field-company_email"]')
  await expect(savedInput).toBeVisible()
  const savedValue = await savedInput.inputValue()
  console.log(`Saved company email: ${savedValue}`)
  expect(savedValue).toBe(testValue)

  // Restore original value and save
  await savedInput.clear()
  await savedInput.fill(originalValue)
  await page.keyboard.press('Tab')
  await page.waitForTimeout(500)
  await page.click('[data-automation-id="AdminCompanySectionView-save-button"]')
  await page.waitForTimeout(1500)

  console.log(`Restored company email to: ${originalValue}`)
})

test('test Xero sales branding theme save, reload, and restore', async ({
  authenticatedPage: page,
}) => {
  await page.goto('/admin/company/xero')

  const selector = autoId(page, 'SectionForm-xero-field-xero_sales_branding_theme_id')
  const emptyMarker = autoId(page, 'SectionForm-xero-field-xero_sales_branding_theme_id-empty')
  const errorMarker = autoId(page, 'SectionForm-xero-field-xero_sales_branding_theme_id-error')

  await expect(selector).toBeVisible({ timeout: 15000 })
  // The select is enabled-and-empty for a beat before the themes fetch settles, so
  // toBeEnabled alone is not a sound sync point. Poll until the load has resolved
  // into exactly one of: error, empty, or ready.
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

  // A load error means a broken Xero connection — fail loudly, don't skip.
  await expect(errorMarker).toBeHidden()
  test.skip(await emptyMarker.isVisible(), 'The connected Xero tenant has no branding themes')
  await expect(selector).toBeEnabled()

  const originalValue = await selector.inputValue()
  const availableThemeIds = await selector
    .locator('option')
    .evaluateAll((options) =>
      options
        .filter(
          (option) => option.value !== '' && !option.textContent?.startsWith('Unavailable theme'),
        )
        .map((option) => option.value),
    )

  const differentThemeId = availableThemeIds.find((id) => id !== originalValue)
  const testValue = originalValue === '' ? availableThemeIds[0] : differentThemeId
  test.skip(
    testValue === undefined,
    'The connected Xero tenant has no alternative branding theme to exercise',
  )
  if (testValue === undefined) return

  try {
    await selector.selectOption(testValue)
    await expect(
      page.locator('[data-automation-id="AdminCompanySectionView-save-button"]'),
    ).toBeEnabled()
    await page.click('[data-automation-id="AdminCompanySectionView-save-button"]')
    await expect(
      page.locator('[data-automation-id="AdminCompanySectionView-save-button"]'),
    ).toBeDisabled({ timeout: 10000 })

    await page.reload()
    await expect(selector).toBeVisible({ timeout: 15000 })
    await expect(selector).toHaveValue(testValue)
  } finally {
    // Null means Xero setup is incomplete. Selecting the first live theme
    // completes setup, so never deliberately restore the invalid null state.
    if (originalValue !== '') {
      await page.goto('/admin/company/xero')
      // Wait for the option itself so selectOption below cannot race the themes load.
      await expect(selector.locator(`option[value="${originalValue}"]`)).toBeAttached({
        timeout: 15000,
      })
      if ((await selector.inputValue()) !== originalValue) {
        await selector.selectOption(originalValue)
        await page.click('[data-automation-id="AdminCompanySectionView-save-button"]')
        await expect(
          page.locator('[data-automation-id="AdminCompanySectionView-save-button"]'),
        ).toBeDisabled({ timeout: 10000 })
        await page.reload()
        await expect(selector).toHaveValue(originalValue)
      }
    }
  }
})
