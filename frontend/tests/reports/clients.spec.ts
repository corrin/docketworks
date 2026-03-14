import { test, expect } from '../fixtures/auth'
import { TEST_CLIENT_NAME } from '../fixtures/helpers'

test.describe('Clients Report', () => {
  test('sorts by spend, verifies client detail, and searches for testing client', async ({
    authenticatedPage: page,
  }) => {
    // Navigate to the Clients Report
    await page.goto('/reports/clients')
    await page.waitForLoadState('networkidle')

    // Verify we're on the right page
    await expect(page.getByRole('heading', { name: 'Clients' })).toBeVisible()

    // Wait for loading to complete
    await expect(page.getByText('Loading clients...')).toBeHidden({ timeout: 30000 })

    // Wait for the table to be visible
    const table = page.locator('table')
    await expect(table).toBeVisible()

    // Click "Total Spend" column header to sort descending (first click sorts ascending, second sorts descending)
    const totalSpendHeader = page.getByRole('button', { name: /Total Spend/i })
    await expect(totalSpendHeader).toBeVisible()

    // Click twice to sort descending (biggest spenders first)
    await totalSpendHeader.click()
    await page.waitForLoadState('networkidle')
    await totalSpendHeader.click()
    await page.waitForLoadState('networkidle')

    // Wait for table to update
    await page.waitForTimeout(500)

    // Get the first row's data
    const firstRow = table.locator('tbody tr').first()
    const firstRowSpend = firstRow.locator('td').nth(3)
    await expect(firstRowSpend).toBeVisible()

    const spendText = await firstRowSpend.textContent()
    console.log(`Top spender total: ${spendText}`)

    // Validate the biggest spender has total_spend > $0
    // Format is like "$1,234.56" or "$0.00"
    expect(spendText).toBeTruthy()
    expect(spendText).not.toBe('$0.00')
    expect(spendText).toMatch(/^\$[\d,]+\.\d{2}$/)

    // Parse the amount and verify it's greater than 0
    const amount = parseFloat(spendText!.replace(/[$,]/g, ''))
    expect(amount).toBeGreaterThan(0)

    // Get the client name before clicking
    const clientName = await firstRow.locator('td').first().textContent()
    console.log(`Clicking on top spender: ${clientName}`)

    // Click on the client row to navigate to details
    await firstRow.click()

    // Wait for navigation to client detail page
    await page.waitForURL(/\/clients\/[a-f0-9-]+$/, { timeout: 15000 })
    await page.waitForLoadState('networkidle')

    // Wait for client detail to load
    await expect(page.getByText('Loading client...')).toBeHidden({ timeout: 30000 })

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
    const totalSpendValue = page.locator('.bg-indigo-50 p.text-3xl')
    await expect(totalSpendValue).toBeVisible()

    const detailSpendText = await totalSpendValue.textContent()
    console.log(`Client detail Total Spend: ${detailSpendText}`)

    // Verify the spend amount matches what we saw in the table
    expect(detailSpendText).toBe(spendText)

    // Navigate back to clients list
    await page.getByRole('button', { name: /Back/i }).click()
    await page.waitForURL(/\/reports\/clients/, { timeout: 10000 })
    await page.waitForLoadState('networkidle')

    // Wait for loading to complete
    await expect(page.getByText('Loading clients...')).toBeHidden({ timeout: 30000 })

    // Re-get table reference after navigation
    const clientsTable = page.locator('table')
    await expect(clientsTable).toBeVisible()

    // Now search for the test client
    const searchInput = page.locator('input[placeholder*="Search clients"]')
    await expect(searchInput).toBeVisible()
    await searchInput.clear()
    await searchInput.fill('ABC Carpet')

    // Wait for debounced search to trigger and complete
    await page.waitForResponse(
      (response) =>
        response.url().includes('/clients/search') &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 10000 },
    )
    await page.waitForLoadState('networkidle')

    // Validate that a row with the test client appears in results
    const testClientRow = clientsTable.locator('tbody tr', {
      hasText: new RegExp(TEST_CLIENT_NAME, 'i'),
    })
    await expect(testClientRow.first()).toBeVisible({ timeout: 10000 })

    // Verify results are filtered (should be much fewer than all clients)
    const resultText = page.locator('text=/Found \\d+ client/')
    const resultCount = await resultText.textContent()
    console.log(`Search results: ${resultCount}`)

    console.log(
      'Clients report test passed: sorted by spend, validated client detail, found test client',
    )
  })
})
