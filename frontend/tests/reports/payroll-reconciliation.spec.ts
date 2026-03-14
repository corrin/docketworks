import { test, expect } from '../fixtures/auth'

test.describe('Payroll Reconciliation Report', () => {
  test('loads and displays reconciliation data', async ({ authenticatedPage: page }) => {
    // Navigate to the report
    await page.goto('/reports/payroll-reconciliation')
    await page.waitForLoadState('networkidle')

    // Verify page title
    await expect(page.getByRole('heading', { name: 'Payroll Reconciliation' })).toBeVisible()

    // Use FY 2025-2026 dates (backend returns JM-only weeks where no Xero pay run exists)
    // April 1 2025 is a Tuesday, so date snapping should adjust start to 2025-03-31 (Monday)
    await page.locator('#start-date').fill('2025-04-01')
    await page.locator('#end-date').fill('2026-03-31')
    // Trigger change event
    await page.locator('#end-date').dispatchEvent('change')

    // Wait for the reconciliation API response (date-range snapping happens first)
    const apiResponse = await page.waitForResponse(
      (response) =>
        response.url().includes('/payroll-reconciliation/') && response.status() === 200,
      { timeout: 30000 },
    )

    // Log the raw response for debugging
    const responseBody = await apiResponse.json()
    const weekCount = responseBody.heatmap?.rows?.length ?? 0
    const staffCount = responseBody.heatmap?.staff_names?.length ?? 0
    console.log(`API response: ${weekCount} weeks, ${staffCount} staff`)
    console.log(`Grand totals:`, JSON.stringify(responseBody.grand_totals))

    // Verify dates were snapped (April 1 2025 is Tuesday → should snap to March 31 Monday)
    const startDateValue = await page.locator('#start-date').inputValue()
    expect(startDateValue).toBe('2025-03-31')

    // Verify summary cards are visible with real values
    const xeroTotal = page.locator('[data-automation-id="PayrollReconciliation-xero-total"]')
    await expect(xeroTotal).toBeVisible({ timeout: 10000 })

    const jmTotal = page.locator('[data-automation-id="PayrollReconciliation-jm-total"]')
    await expect(jmTotal).toBeVisible()

    const diffValue = page.locator('[data-automation-id="PayrollReconciliation-diff-value"]')
    await expect(diffValue).toBeVisible()

    // Verify heatmap table is visible
    const heatmapTable = page.locator('[data-automation-id="PayrollReconciliation-heatmap"]')
    await expect(heatmapTable).toBeVisible()

    // Count heatmap rows (weeks) — should have at least 1 week
    const heatmapRows = heatmapTable.locator('tbody tr')
    const rowCount = await heatmapRows.count()
    expect(rowCount).toBeGreaterThan(0)
    console.log(`Heatmap has ${rowCount} week rows`)

    // Count staff columns — should have at least 1
    const staffHeaders = heatmapTable.locator('thead th')
    const colCount = await staffHeaders.count()
    // First column is "Week" label, rest are staff names
    const displayedStaffCount = colCount - 1
    console.log(`Heatmap has ${displayedStaffCount} staff columns`)
    expect(displayedStaffCount).toBeGreaterThan(0)

    // Verify at least some cells have dollar values (not all empty/null)
    const cellsWithValues = heatmapTable.locator('tbody td:not(:first-child) span')
    const totalCells = await cellsWithValues.count()
    let nonEmptyCells = 0
    for (let i = 0; i < Math.min(totalCells, 50); i++) {
      const text = await cellsWithValues.nth(i).textContent()
      if (text && text.trim() !== '') nonEmptyCells++
    }
    console.log(`Found ${nonEmptyCells} non-empty cells in first 50 checked`)
    expect(nonEmptyCells).toBeGreaterThan(0)

    console.log(
      `Payroll Reconciliation test passed: ${rowCount} weeks, ${displayedStaffCount} staff, ${nonEmptyCells}+ cells with data`,
    )
  })
})
