import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

test.describe('Sales Forecast Report', () => {
  test('displays sales forecast data on load', async ({ authenticatedPage: page }) => {
    // Navigate to the Sales Forecast Report
    await page.goto('/reports/sales-forecast')
    await page.waitForLoadState('networkidle')

    // Verify we're on the right page
    await expect(autoId(page, 'SalesForecastReport-title')).toContainText('Sales Forecast Report')

    // Wait for loading to complete
    await autoId(page, 'SalesForecastReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    // Verify summary cards are visible
    await expect(autoId(page, 'SalesForecastReport-summary-cards')).toBeVisible()

    // Check "Total Xero Sales" card has currency value
    const xeroSalesValue = autoId(page, 'SalesForecastReport-xero-sales-value')
    await expect(xeroSalesValue).toBeVisible()
    const xeroSalesText = await xeroSalesValue.textContent()
    expect(xeroSalesText).toMatch(/^\$[\d,]+\.\d{2}$/)

    // Check "Total JM Sales" card has currency value
    const jmSalesValue = autoId(page, 'SalesForecastReport-jm-sales-value')
    await expect(jmSalesValue).toBeVisible()
    const jmSalesText = await jmSalesValue.textContent()
    expect(jmSalesText).toMatch(/^\$[\d,]+\.\d{2}$/)

    // Check "Total Variance" card has currency value (can be negative)
    const varianceValue = autoId(page, 'SalesForecastReport-variance-value')
    await expect(varianceValue).toBeVisible()
    const varianceText = await varianceValue.textContent()
    expect(varianceText).toMatch(/^-?\$[\d,]+\.\d{2}$/)

    // Check "Avg Variance %" card has percentage
    const avgVarianceValue = autoId(page, 'SalesForecastReport-avg-variance-value')
    await expect(avgVarianceValue).toBeVisible()
    const avgVarianceText = await avgVarianceValue.textContent()
    expect(avgVarianceText).toMatch(/^-?[\d.]+%$/)

    // Verify the data table is visible
    await expect(autoId(page, 'SalesForecastReport-table')).toBeVisible()

    // Verify at least one data row exists
    const tableRows = autoId(page, 'SalesForecastReport-table').locator('tbody tr')
    const rowCount = await tableRows.count()
    expect(rowCount).toBeGreaterThan(0)

    console.log(`Sales Forecast Report test passed with ${rowCount} month rows displayed`)
  })
})
