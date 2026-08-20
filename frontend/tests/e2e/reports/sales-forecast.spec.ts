import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * The forecast compares Xero invoice totals with Job Manager revenue, so the
 * cross-layer risk is the drill-down: the month row the user clicks has to
 * become the path segment the detail endpoint validates, and the rows that
 * come back have to survive the client-side sort. Both are asserted here
 * because neither the unit test (which serves its own fixture) nor the API
 * test (which never clicks a row) can see them meet.
 *
 * Navigation goes through the menu rather than page.goto: the Reports menu is
 * gated on is_office_staff, and a spec that jumps straight to the URL proves
 * the page renders while leaving it unreachable.
 */

const CURRENCY = /^-?\$[\d,]+\.\d{2}$/
const PERCENTAGE = /^-?[\d.]+%$/
const COMPANY_COLUMN = 3

test.describe('Sales Forecast Report', () => {
  test('opens from the Reports menu, drills into a month and sorts the detail', async ({
    authenticatedPage: page,
  }) => {
    await autoId(page, 'AppNavbar-reports-menu').click()
    const link = autoId(page, 'AppNavbar-sales-forecast')
    await expect(link).toBeVisible()
    await link.click()

    await expect(page).toHaveURL(/\/reports\/sales-forecast$/)
    await expect(autoId(page, 'SalesForecastReport-title')).toContainText('Sales Forecast Report')
    await autoId(page, 'SalesForecastReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    await expect(autoId(page, 'SalesForecastReport-summary-cards')).toBeVisible()
    await expect(autoId(page, 'SalesForecastReport-xero-sales-value')).toHaveText(CURRENCY)
    await expect(autoId(page, 'SalesForecastReport-jm-sales-value')).toHaveText(CURRENCY)
    await expect(autoId(page, 'SalesForecastReport-variance-value')).toHaveText(CURRENCY)
    await expect(autoId(page, 'SalesForecastReport-avg-variance-value')).toHaveText(PERCENTAGE)

    const monthRows = autoId(page, 'SalesForecastReport-table').locator('tbody tr')
    await expect(monthRows.first()).toBeVisible()
    const monthLabel = (await monthRows.first().locator('td').first().innerText()).trim()

    await monthRows.first().click()

    // The clicked month, not merely "a month": the label proves the row's
    // YYYY-MM survived the round trip through the path parameter.
    await expect(autoId(page, 'SalesForecastReport-detail-month')).toHaveText(monthLabel)
    await autoId(page, 'SalesForecastReport-detail-loading').waitFor({
      state: 'hidden',
      timeout: 30000,
    })

    const detailTable = autoId(page, 'SalesForecastReport-detail-table')
    await expect(detailTable.locator('tbody tr').first()).toBeVisible()

    const companies = async (): Promise<string[]> =>
      (await detailTable.locator(`tbody tr td:nth-child(${COMPANY_COLUMN})`).allInnerTexts()).map(
        (cell) => cell.trim(),
      )

    await autoId(page, 'SalesForecastReport-header-company').locator('button').click()
    const ascending = await companies()
    expect(ascending).toEqual(ascending.toSorted((a, b) => a.localeCompare(b)))

    await autoId(page, 'SalesForecastReport-header-company').locator('button').click()
    const descending = await companies()
    expect(descending).toEqual(ascending.toReversed())

    await autoId(page, 'SalesForecastReport-back').click()
    await expect(autoId(page, 'SalesForecastReport-table')).toBeVisible()
    await expect(detailTable).toBeHidden()
  })
})
