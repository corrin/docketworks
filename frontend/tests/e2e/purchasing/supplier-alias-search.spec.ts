import { test, expect } from '../fixtures/auth'
import { autoId, waitForCompanyCreateResponse } from '../helpers'

/**
 * Supplier alias search.
 *
 * Supplier names on paperwork or in Xero don't always match the canonical
 * `Company.name` in the CRM, so staff attach search aliases to a company
 * (`CompanyDetailPage`'s "Supplier Aliases" tab) and the PO-creation supplier
 * picker (`CompanyLookup` in supplier mode, over
 * `/api/purchasing/suppliers/search/`) matches on name OR active alias.
 *
 * The fixture creates its own company via `CompanyLookup`'s Ctrl+Enter
 * quick-create, which synchronously pushes to Xero — the live-Xero
 * touchpoint this spec carries, same as `crm/people` and
 * `create-job-with-new-company`; nothing about alias search itself talks to
 * Xero (`SupplierSearchAlias` is a plain local model).
 */
test.describe('Supplier alias search', () => {
  test('an alias added on the company detail page resolves to the canonical supplier in PO creation', async ({
    authenticatedPage: page,
  }) => {
    const randomSuffix = Math.floor(Math.random() * 100000)
    const supplierName = `[TEST] Alias Supplier ${randomSuffix}`
    const aliasName = `[TEST] Alias Nickname ${randomSuffix}`

    // Create a fresh supplier via PO create's Ctrl+Enter quick-create.
    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const poSupplierInput = autoId(page, 'CompanyLookup-input')
    await poSupplierInput.click()
    await poSupplierInput.fill(supplierName)
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'CompanyLookup-create-new').waitFor({ timeout: 5000 })
    const created = await waitForCompanyCreateResponse(page, async () => {
      await poSupplierInput.press('Control+Enter')
    })
    expect(created.name).toBe(supplierName)
    await expect(autoId(page, 'CompanyLookup-xero-valid')).toBeVisible({ timeout: 10000 })

    // Find the new company in the CRM list and open its detail page.
    await page.goto('/crm/companies')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Loading companies...')).toBeHidden({ timeout: 30000 })

    const companiesTable = autoId(page, 'CompaniesTable-table')
    await expect(companiesTable).toBeVisible()

    const crmSearchInput = autoId(page, 'CompaniesTable-search')
    await expect(crmSearchInput).toBeVisible()
    const companySearchResponse = page.waitForResponse(
      (response) => response.url().includes('/companies/search') && response.status() === 200,
      { timeout: 10000 },
    )
    await crmSearchInput.fill(supplierName)
    await companySearchResponse

    const companyRow = companiesTable.locator('tbody tr', { hasText: supplierName })
    await expect(companyRow.first()).toBeVisible({ timeout: 10000 })
    await companyRow.first().click()

    await page.waitForURL(/\/crm\/companies\/[a-f0-9-]+$/, { timeout: 15000 })
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Loading company...')).toBeHidden({ timeout: 30000 })

    // Add a search alias on the new "Supplier Aliases" tab.
    await autoId(page, 'CompanyDetail-tab-suppliers').click()
    await expect(page.getByText('No search aliases yet.')).toBeVisible({ timeout: 10000 })

    await autoId(page, 'CompanyDetail-alias-input').fill(aliasName)
    const aliasCreateResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/supplier-aliases/') &&
        response.request().method() === 'POST' &&
        response.status() === 201,
      { timeout: 10000 },
    )
    await autoId(page, 'CompanyDetail-alias-add').click()
    await aliasCreateResponse

    await expect(page.getByText(aliasName)).toBeVisible({ timeout: 10000 })

    // Back on PO create, searching by the alias must resolve to the
    // canonical company — not the alias text itself.
    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    const poSupplierInput2 = autoId(page, 'CompanyLookup-input')
    await poSupplierInput2.click()
    const supplierSearchResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/purchasing/suppliers/search/') && response.status() === 200,
      { timeout: 10000 },
    )
    await poSupplierInput2.fill(aliasName)
    await supplierSearchResponse
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })

    const supplierOption = page.getByRole('option', { name: supplierName })
    await expect(supplierOption).toBeVisible({ timeout: 10000 })
    await supplierOption.click()

    await expect(poSupplierInput2).toHaveValue(supplierName)
  })
})
