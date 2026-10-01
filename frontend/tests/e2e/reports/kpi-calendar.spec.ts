import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * Reads cost lines only: a run of this spec spends no Xero quota.
 *
 * The cross-layer risks are the hops neither the unit test (which serves its
 * own fixture) nor the API test (which never clicks) can see: the month the
 * nav writes into the URL has to become the query the server answers, the
 * day a user clicks has to open the dialog carrying that day's figures, and
 * the job number inside it has to land on the job. The figure that travels
 * from cell to dialog is asserted string-equal, which is what the one shared
 * formatter exists to guarantee.
 *
 * Navigation goes through the menu rather than page.goto: the Reports menu is
 * gated on is_office_staff, and a spec that jumps straight to the URL proves
 * the page renders while leaving it unreachable.
 *
 * Fable: which month carries work, this spec cannot choose — the current
 * month may be a day old, and the job-creating specs sharing this database
 * put their lines wherever today falls. It walks back month by month until a
 * weekday cell shows billed hours, which is the signal a day has job rows,
 * and fails loudly if two years hold none rather than asserting nothing.
 */

const WHOLE_CURRENCY = /-?\$[\d,]+/
const HOURS = /\d+h( \d+m)?|\d+m/
const MONTHS_TO_SEARCH = 24

test.describe('KPI Calendar', () => {
  test('opens from the Reports menu, steps back a month, opens a day and reaches its job', async ({
    authenticatedPage: page,
  }) => {
    await autoId(page, 'AppNavbar-reports-menu').click()
    const link = autoId(page, 'AppNavbar-kpi-calendar')
    await expect(link).toBeVisible()
    await link.click()

    // Every setting is in the URL from the first paint: a bare /reports/kpi
    // is redirected to name this month, the ladder and the precision, so a
    // copied link always reopens on what it showed.
    await expect(page).toHaveURL(/\/reports\/kpi\?/)
    await expect(page).toHaveURL(/[?&]month=\d{4}-\d{2}/)
    await expect(page).toHaveURL(/[?&]target=hours/)
    await expect(page).toHaveURL(/[?&]decimals=0/)
    await expect(autoId(page, 'KpiCalendarReport-title')).toHaveText('KPI Calendar')
    await autoId(page, 'KpiCalendarReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    await expect(autoId(page, 'KpiCalendarReport-summary-cards')).toBeVisible()
    await expect(autoId(page, 'KpiCalendarReport-card-labour-value')).toContainText(HOURS)
    await expect(autoId(page, 'KpiCalendarReport-card-material-value')).toContainText(
      WHOLE_CURRENCY,
    )
    await expect(autoId(page, 'KpiCalendarReport-card-adjustment-value')).toContainText(
      WHOLE_CURRENCY,
    )
    await expect(autoId(page, 'KpiCalendarReport-card-profit-value')).toContainText(WHOLE_CURRENCY)
    await expect(autoId(page, 'KpiCalendarReport-grid')).toBeVisible()

    // A cell that billed hours, by the attribute the cell carries for this:
    // its text runs "6h" and "billable" together, so a text match is not
    // the signal.
    const workedCells = page.locator(
      '[data-automation-id^="KpiCalendarReport-day-"][data-billable-hours]:not([data-billable-hours="0"])',
    )

    let stepped = 0
    while ((await workedCells.count()) === 0) {
      expect(stepped, 'no month in two years showed a day with billed hours').toBeLessThan(
        MONTHS_TO_SEARCH,
      )
      const before = await autoId(page, 'KpiCalendarReport-month-label').innerText()
      await autoId(page, 'KpiCalendarReport-prev').click()
      stepped += 1
      // The month is the URL's, and the previous month stays on screen dimmed
      // (aria-busy) until the new one answers.
      await expect(page).toHaveURL(/[?&]month=\d{4}-\d{2}/)
      await expect(autoId(page, 'KpiCalendarReport-month-label')).not.toHaveText(before)
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30000 })
    }

    const cell = workedCells.first()
    const cellId = await cell.getAttribute('data-automation-id')
    expect(cellId).not.toBeNull()
    const cellGrossProfit = (await autoId(page, `${cellId}-gp`).innerText()).trim()
    await cell.click()

    const dialog = autoId(page, 'KpiDayDetailsDialog-container')
    await expect(dialog).toBeVisible()
    // The same figure, through the same formatter: the dialog does not
    // recompute what the cell showed.
    await expect(autoId(page, 'KpiDayDetailsDialog-gross-profit')).toHaveText(cellGrossProfit)

    const jobLink = dialog.locator('[data-automation-id^="KpiDayDetailsDialog-job-"]').first()
    await expect(jobLink).toBeVisible()
    const jobId = (await jobLink.getAttribute('data-automation-id'))?.replace(
      'KpiDayDetailsDialog-job-',
      '',
    )
    await jobLink.click()
    await expect(page).toHaveURL(new RegExp(`/jobs/${jobId}$`))
  })

  test('carries the ladder and precision settings in the URL', async ({
    authenticatedPage: page,
  }) => {
    await autoId(page, 'AppNavbar-reports-menu').click()
    await autoId(page, 'AppNavbar-kpi-calendar').click()
    await autoId(page, 'KpiCalendarReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    await autoId(page, 'KpiCalendarReport-target-dollars').click()
    await expect(page).toHaveURL(/[?&]target=dollars/)
    await expect(autoId(page, 'KpiCalendarReport-target-dollars')).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    await autoId(page, 'KpiCalendarReport-decimals-2').click()
    await expect(page).toHaveURL(/[?&]decimals=2/)
    // Cents everywhere once asked: the card and every cell.
    await expect(autoId(page, 'KpiCalendarReport-card-material-value')).toContainText(
      /-?\$[\d,]+\.\d{2}/,
    )
    const anyGrossProfit = page
      .locator('[data-automation-id^="KpiCalendarReport-day-"][data-automation-id$="-gp"]')
      .first()
    await expect(anyGrossProfit).toHaveText(/^-?\$[\d,]+\.\d{2}$/)

    // The settings survive a reload: they are the URL's, not the page's.
    await page.reload()
    await autoId(page, 'KpiCalendarReport-loading').waitFor({ state: 'hidden', timeout: 30000 })
    await expect(autoId(page, 'KpiCalendarReport-target-dollars')).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await expect(anyGrossProfit).toHaveText(/^-?\$[\d,]+\.\d{2}$/)
  })
})
