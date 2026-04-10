import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

test.describe('WIP Report', () => {
  test('displays wip data on load', async ({ authenticatedPage: page }) => {
    await page.goto('/reports/wip')
    await page.waitForLoadState('networkidle')

    // Verify page title
    await expect(autoId(page, 'WIPReport-title')).toContainText('WIP Report')

    // Wait for loading to complete
    await autoId(page, 'WIPReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    // Verify summary cards are visible
    await expect(autoId(page, 'WIPReport-summary-cards')).toBeVisible()

    // Check "Total Gross WIP" has currency value
    const totalGrossValue = autoId(page, 'WIPReport-total-gross-value')
    await expect(totalGrossValue).toBeVisible()
    const grossText = await totalGrossValue.textContent()
    expect(grossText).toMatch(/^-?\$[\d,]+\.\d{2}$/)

    // Check "Total Net WIP" has currency value
    const totalNetValue = autoId(page, 'WIPReport-total-net-value')
    await expect(totalNetValue).toBeVisible()
    const netText = await totalNetValue.textContent()
    expect(netText).toMatch(/^-?\$[\d,]+\.\d{2}$/)

    // Verify the data table is visible with at least one row
    await expect(autoId(page, 'WIPReport-table')).toBeVisible()
    const tableRows = autoId(page, 'WIPReport-table').locator('tbody tr')
    const rowCount = await tableRows.count()
    expect(rowCount).toBeGreaterThan(0)

    console.log(`WIP Report test passed with ${rowCount} job rows displayed`)
  })
})
