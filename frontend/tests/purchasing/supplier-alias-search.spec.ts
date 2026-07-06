import { test, expect } from '../fixtures/auth'
import { autoId, waitForCompanyCreateResponse } from '../fixtures/helpers'

test.describe('supplier alias search', () => {
  test('adds a supplier alias and finds the supplier from PO lookup', async ({
    authenticatedPage: page,
  }) => {
    const suffix = Date.now()
    const supplierName = `S&T Stainless Limited ${suffix}`
    const alias = `Steel and Tube ${suffix}`

    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const supplierInput = autoId(page, 'CompanyLookup-input')
    await supplierInput.click()
    await supplierInput.fill(supplierName)
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'CompanyLookup-create-new').waitFor({ timeout: 5000 })
    await waitForCompanyCreateResponse(page, async () => {
      await supplierInput.press('Control+Enter')
    })
    await autoId(page, 'CompanyLookup-xero-valid').waitFor({ timeout: 30000 })
    await expect(supplierInput).toHaveValue(supplierName)

    await page.goto('/crm/companies')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Loading companies...')).toBeHidden({ timeout: 30000 })

    const companySearchInput = page.locator('input[placeholder*="Search companies"]')
    await companySearchInput.fill(supplierName)
    const companyRow = page.locator('tbody tr', { hasText: supplierName }).first()
    await expect(companyRow).toBeVisible({ timeout: 10000 })
    await companyRow.click()
    await page.waitForURL(/\/crm\/companies\/[a-f0-9-]+$/, { timeout: 15000 })
    await expect(page.getByRole('heading', { name: supplierName })).toBeVisible({
      timeout: 30000,
    })

    const aliasInput = autoId(page, 'CompanyDetailView-alias-input')
    await aliasInput.fill(alias)
    await autoId(page, 'CompanyDetailView-alias-add').click()
    await expect(page.getByText(alias)).toBeVisible({ timeout: 10000 })

    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const poSupplierInput = autoId(page, 'CompanyLookup-input')
    await poSupplierInput.fill(alias)
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await expect(page.getByRole('option').first()).toHaveText(supplierName)
    await page.getByRole('option').first().click()
    await expect(poSupplierInput).toHaveValue(supplierName)

    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const punctuationQuery = `S & T Stainless Limited ${suffix}`
    await autoId(page, 'CompanyLookup-input').fill(punctuationQuery)
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await expect(page.getByRole('option').first()).toHaveText(supplierName)
  })
})
