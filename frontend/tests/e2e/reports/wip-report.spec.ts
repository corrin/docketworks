import type { WipResponse } from '../../../src/api/generated/types.gen'
import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

test.describe('WIP Report', () => {
  test('displays wip data on load', async ({ authenticatedPage: page }) => {
    const report = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/accounting/reports/wip/' &&
        response.status() === 200,
    )
    await page.goto('/reports/wip')
    await page.waitForLoadState('networkidle')

    await expect(autoId(page, 'WIPReport-title')).toContainText('WIP Report')

    await autoId(page, 'WIPReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    await expect(autoId(page, 'WIPReport-summary-cards')).toBeVisible()

    // The page renders one report response; the cards and the table must show
    // that response. A currency-shaped regex passed on any number, including
    // a total that ignored every row.
    const body: WipResponse = await (await report).json()
    const nzd = new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' })
    await expect(autoId(page, 'WIPReport-total-gross-value')).toHaveText(
      nzd.format(body.summary.total_gross),
    )
    await expect(autoId(page, 'WIPReport-total-net-value')).toHaveText(
      nzd.format(body.summary.total_net),
    )

    await expect(autoId(page, 'WIPReport-table')).toBeVisible()
    await expect(autoId(page, 'WIPReport-table').locator('tbody tr')).toHaveCount(body.jobs.length)
  })
})
