import { test, expect } from '../fixtures/auth'
import { autoId, waitForClientCreateResponse } from '../fixtures/helpers'

test.describe('supplier alias search', () => {
  test('adds a supplier alias and finds the supplier from PO lookup', async ({
    authenticatedPage: page,
  }) => {
    const suffix = Date.now()
    const supplierName = `S&T Stainless Limited ${suffix}`
    const alias = `Steel and Tube ${suffix}`

    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const supplierInput = autoId(page, 'ClientLookup-input')
    await supplierInput.click()
    await supplierInput.fill(supplierName)
    await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'ClientLookup-create-new').waitFor({ timeout: 5000 })
    await waitForClientCreateResponse(page, async () => {
      await supplierInput.press('Control+Enter')
    })
    await autoId(page, 'ClientLookup-xero-valid').waitFor({ timeout: 30000 })
    await expect(supplierInput).toHaveValue(supplierName)

    await page.goto('/crm/clients')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Loading clients...')).toBeHidden({ timeout: 30000 })

    const clientSearchInput = page.locator('input[placeholder*="Search clients"]')
    await clientSearchInput.fill(supplierName)
    const clientRow = page.locator('tbody tr', { hasText: supplierName }).first()
    await expect(clientRow).toBeVisible({ timeout: 10000 })
    await clientRow.click()
    await page.waitForURL(/\/crm\/clients\/[a-f0-9-]+$/, { timeout: 15000 })
    await expect(page.getByRole('heading', { name: supplierName })).toBeVisible({
      timeout: 30000,
    })

    const aliasInput = autoId(page, 'ClientDetailView-alias-input')
    await aliasInput.fill(alias)
    await autoId(page, 'ClientDetailView-alias-add').click()
    await expect(page.getByText(alias)).toBeVisible({ timeout: 10000 })

    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const poSupplierInput = autoId(page, 'ClientLookup-input')
    await poSupplierInput.fill(alias)
    await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
    await expect(page.getByRole('option').first()).toHaveText(supplierName)
    await page.getByRole('option').first().click()
    await expect(poSupplierInput).toHaveValue(supplierName)

    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const punctuationQuery = `S & T Stainless Limited ${suffix}`
    await autoId(page, 'ClientLookup-input').fill(punctuationQuery)
    await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
    await expect(page.getByRole('option').first()).toHaveText(supplierName)
  })
})
