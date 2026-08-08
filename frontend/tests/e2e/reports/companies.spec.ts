import debug from 'debug'
import { test, expect } from '../fixtures/auth'
import { autoId, TEST_COMPANY_NAME } from '../helpers'

const log = debug('e2e:reports')

test.describe('Companies Report', () => {
  test('sorts by spend, verifies company detail, and searches for testing company', async ({
    authenticatedPage: page,
  }) => {
    // Navigate to the Companies page
    await page.goto('/crm/companies')
    await page.waitForLoadState('networkidle')

    // Verify we're on the right page
    await expect(page.getByRole('heading', { name: 'Companies' })).toBeVisible()

    // Wait for loading to complete
    await expect(page.getByText('Loading companies...')).toBeHidden({ timeout: 30000 })

    // Wait for the table to be visible
    const table = autoId(page, 'CompaniesTable-table')
    await expect(table).toBeVisible()

    // Click "Total Spend" column header to sort descending (first click sorts ascending, second sorts descending)
    const totalSpendHeader = autoId(page, 'CompaniesTable-header-total-spend')
    await expect(totalSpendHeader).toBeVisible()

    // Click twice to sort descending (biggest spenders first). Each waiter is
    // registered before its click and keyed on the sort_dir it should
    // produce, so the row read below cannot see a stale ordering.
    const sortedResponse = (dir: 'asc' | 'desc') =>
      page.waitForResponse(
        (response) =>
          response.url().includes('/companies/search') &&
          response.url().includes(`sort_dir=${dir}`) &&
          response.status() === 200,
        { timeout: 10000 },
      )
    await Promise.all([sortedResponse('asc'), totalSpendHeader.click()])
    await Promise.all([sortedResponse('desc'), totalSpendHeader.click()])

    // Get the first row's data
    const firstRow = table.locator('tbody tr').first()
    const companyId = await firstRow.getAttribute('data-company-id')
    if (!companyId) {
      throw new Error('Companies table row is missing data-company-id')
    }

    const firstRowSpend = autoId(page, `CompaniesTable-cell-${companyId}-total-spend`)
    await expect(firstRowSpend).toBeVisible()

    const spendText = await firstRowSpend.textContent()

    // Validate the biggest spender has total_spend > $0
    // Format is like "$1,234.56" or "$0.00"
    expect(spendText).toBeTruthy()
    expect(spendText).not.toBe('$0.00')
    expect(spendText).toMatch(/^\$[\d,]+\.\d{2}$/)

    // Parse the amount and verify it's greater than 0
    const amount = parseFloat(spendText!.replace(/[$,]/g, ''))
    expect(amount).toBeGreaterThan(0)

    // Get the company name before clicking
    const companyName = await autoId(page, `CompaniesTable-cell-${companyId}-name`).textContent()
    log(`Clicking on top spender: ${companyName}`)

    // Click on the company row to navigate to details
    await firstRow.click()

    // Wait for navigation to company detail page
    await page.waitForURL(/\/crm\/companies\/[a-f0-9-]+$/, { timeout: 15000 })
    await page.waitForLoadState('networkidle')

    // Wait for company detail to load
    await expect(page.getByText('Loading company...')).toBeHidden({ timeout: 30000 })

    // Click on Financial Summary tab
    const financialTab = page.getByRole('tab', { name: /Financial Summary/i })
    await expect(financialTab).toBeVisible()
    await financialTab.click()

    // Wait for tab content to appear
    await page.waitForTimeout(500)

    // Find the Total Spend value in the Financial Summary tab
    const totalSpendLabel = page.locator('label:text("Total Spend")')
    await expect(totalSpendLabel).toBeVisible()

    // Get the total spend value (it's in the sibling p element with large text)
    const totalSpendValue = autoId(page, 'CompanyDetail-total-spend')
    await expect(totalSpendValue).toBeVisible()

    const detailSpendText = await totalSpendValue.textContent()

    // Verify the spend amount matches what we saw in the table
    expect(detailSpendText).toBe(spendText)

    // Navigate back to companies list
    await autoId(page, 'CompanyDetail-back').click()
    await page.waitForURL(/\/crm\/companies$/, { timeout: 10000 })
    await page.waitForLoadState('networkidle')

    // Wait for loading to complete
    await expect(page.getByText('Loading companies...')).toBeHidden({ timeout: 30000 })

    // Re-get table reference after navigation
    const companiesTable = autoId(page, 'CompaniesTable-table')
    await expect(companiesTable).toBeVisible()

    // Now search for the test company
    const searchInput = autoId(page, 'CompaniesTable-search')
    await expect(searchInput).toBeVisible()
    await searchInput.clear()

    // The waiter is registered before the fill and keyed on the query text,
    // so the debounced request cannot slip past it.
    const filteredResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/companies/search') &&
        response.url().includes('q=ABC') &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 10000 },
    )
    await searchInput.fill('ABC Carpet')
    await filteredResponse

    // Validate that a row with the test company appears in results
    const testCompanyRow = companiesTable.locator('tbody tr', {
      hasText: new RegExp(TEST_COMPANY_NAME, 'i'),
    })
    await expect(testCompanyRow.first()).toBeVisible({ timeout: 10000 })
  })
})
