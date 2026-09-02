import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { getPostableWeek } from '../fixtures/api'
// The app's own formatter: the title renders through it, and the E2E rule is
// cross-page string equality on formatted values (ADR 0046).
import { formatDate } from '../../../src/lib/format'
import { autoId } from '../helpers'

/**
 * The money reconciliation: what DocketWorks expects Xero to pay for a week,
 * beside what Xero computed.
 *
 * This route READS XERO LIVE. It resolves the week's pay run and its pay slips
 * from Xero rather than the synced mirror, because the mirror only exists once
 * a run is Posted and a sync has copied it — blank in the minutes after
 * posting, which is exactly when a mistake is still cheap to fix. So unlike the
 * other report specs this one is not a mirror-table read, and per ADR 0050 it
 * must not be made to fake the call it exists to cover.
 */

const CURRENCY = /^-?\$[\d,]+\.\d{2}$/

async function openReconciliation(page: Page, week: string) {
  await page.goto(`/reports/payroll-reconciliation?week=${week}`)
  await autoId(page, 'PayrollReconciliation-loading').waitFor({
    state: 'hidden',
    timeout: 120000,
  })
}

test.describe('payroll reconciliation', () => {
  test('shows our dollars beside Xero’s for the week', async ({ authenticatedPage: page }) => {
    const week = await getPostableWeek(page)
    await openReconciliation(page, week)

    await expect(autoId(page, 'PayrollReconciliation-title')).toContainText(formatDate(week))
    await expect(autoId(page, 'PayrollReconciliation-summary-cards')).toBeVisible()

    // Both sides as money, because the difference between them is the answer.
    for (const id of ['PayrollReconciliation-total-ours', 'PayrollReconciliation-total-xero']) {
      await expect(autoId(page, id)).toHaveText(CURRENCY)
    }

    // Opus: The count is asserted as a NUMBER, not as zero. Whether the demo
    // tenant is currently paying anyone we did not post for is data, and
    // pinning it to a value would make this spec fail on a healthy week or
    // pass on a broken one.
    await expect(autoId(page, 'PayrollReconciliation-unposted-count')).toHaveText(/^\d+$/)
  })

  test('the wage basis switches which DocketWorks figure is shown', async ({
    authenticatedPage: page,
  }) => {
    const week = await getPostableWeek(page)
    await openReconciliation(page, week)

    const total = autoId(page, 'PayrollReconciliation-total-ours')
    const base = await total.textContent()

    await autoId(page, 'PayrollReconciliation-wageBasis-loaded').click()
    // Opus: The warning is the point of the toggle having two states. The
    // loaded rate allocates paid non-worked time absent from this week's gross, so the
    // difference column stops being a reconciliation — the page has to say so
    // rather than let someone read a variance off it.
    await expect(autoId(page, 'PayrollReconciliation-loadedNote')).toBeVisible()
    const loaded = await total.textContent()

    expect(loaded).not.toBe(base)

    await autoId(page, 'PayrollReconciliation-wageBasis-base').click()
    await expect(autoId(page, 'PayrollReconciliation-loadedNote')).toHaveCount(0)
    await expect(total).toHaveText(base ?? '')
  })

  test('the weekly payroll panel links here for the week it is showing', async ({
    authenticatedPage: page,
  }) => {
    const week = await getPostableWeek(page)
    await page.goto(`/timesheets/weekly?week=${week}`)
    await autoId(page, 'WeeklyOverview-table').waitFor({ timeout: 30000 })

    await autoId(page, 'PayrollPanel-checkTheMoney').click()

    // The week carries across: landing on today's week instead would quietly
    // reconcile a different one from the hours the operator was just looking at.
    await expect(page).toHaveURL(new RegExp(`/reports/payroll-reconciliation\\?week=${week}`))
    await expect(autoId(page, 'PayrollReconciliation-title')).toContainText(formatDate(week))
  })
})
