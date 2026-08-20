import { readFileSync } from 'fs'

import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * Opus: the forecast compares Xero invoice totals with Job Manager revenue, so the
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
    const monthCount = await monthRows.count()
    const monthLabel = (await monthRows.first().locator('td').first().innerText()).trim()

    // The export is a browser download, so nothing below the button is
    // reachable from a component test: the blob, the filename and the click
    // only exist in a real page.
    const download = await Promise.all([
      page.waitForEvent('download'),
      autoId(page, 'SalesForecastReport-export').click(),
    ]).then(([event]) => event)
    expect(download.suggestedFilename()).toMatch(/^sales-forecast-report-\d{4}-\d{2}-\d{2}\.csv$/)
    const csvPath = await download.path()
    const csvLines = readFileSync(csvPath, 'utf8').trim().split('\r\n')
    expect(csvLines[0]).toBe('Month,Xero Sales,JM Sales,Variance,Variance %')
    // One line per month on screen, and the same first month: the export has
    // to be the table the user is looking at, not a second fetch of its own.
    expect(csvLines).toHaveLength(monthCount + 1)
    expect(csvLines[1]).toContain(monthLabel)

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

    // By automation id, not column position: the column order is incidental
    // (COLUMNS in SalesForecastDetailTable), so an inserted column would move
    // an nth-child assertion onto different data without failing.
    const companies = async (): Promise<string[]> =>
      (await autoId(page, 'SalesForecastReport-detail-company').allInnerTexts()).map((cell) =>
        cell.trim(),
      )

    await autoId(page, 'SalesForecastReport-header-company').locator('button').click()
    const ascending = await companies()
    // Both order assertions below hold trivially for a single row, so the
    // month must actually carry several before they mean anything.
    expect(ascending.length).toBeGreaterThan(1)
    expect(ascending).toEqual(
      ascending.toSorted((a, b) => a.localeCompare(b, undefined, { numeric: true })),
    )

    await autoId(page, 'SalesForecastReport-header-company').locator('button').click()
    const descending = await companies()
    expect(descending).toEqual(ascending.toReversed())
    // ...and a reversal that changed nothing would satisfy the line above.
    expect(descending).not.toEqual(ascending)

    await autoId(page, 'SalesForecastReport-back').click()
    await expect(autoId(page, 'SalesForecastReport-table')).toBeVisible()
    await expect(detailTable).toBeHidden()
  })
})
