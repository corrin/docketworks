import { test, expect } from '../fixtures/auth'
import {
  addAdjustmentCostLine,
  autoId,
  createTestJob,
  openJobCostingTab,
  waitForCostLineRow,
} from '../helpers'

/**
 * Copy from Estimate on the Quote tab (KAN-346). One shared fixed-price job,
 * serial: each test builds on the quote state the previous one left.
 *
 * The three server answers, each exercised through the UI:
 * - blank quote (the $0 creation seed) -> copied silently, no dialog;
 * - priced quote -> the archive-and-replace dialog, confirmed;
 * - quote already matching the estimate -> a no-op answer, so a double press
 *   never stacks a second identical archive.
 *
 * The grid helpers live in ../helpers: they were duplicated across three
 * specs (ADR 0039).
 */

test.describe.serial('copy estimate to quote', () => {
  test.setTimeout(120000)
  // The priced-quote test presses Copy expecting the server's 409 — that is
  // the contract's "archive first" answer, and the browser logs the refused
  // request as a resource error before the UI turns it into the dialog.
  test.use({ expectedConsoleErrors: [/the server responded with a status of 409/] })

  let jobUrl: string

  test('one press copies the estimate over the $0 creation seed, no dialog', async ({
    authenticatedPage: page,
  }) => {
    jobUrl = await createTestJob(page, 'CopyEstimate', { pricing: 'fixed_price' })

    await openJobCostingTab(page, jobUrl, 'estimate')
    await addAdjustmentCostLine(page, 'Estimate Details', 'Straightening charge', '1', '100')

    // KAN-349: the Estimate tab shows the server-owned summary — the $100
    // adjustment cost must land in it (revenue derivation is unit-tested).
    await expect(autoId(page, 'JobEstimateTab-summary')).toContainText('$100.00', {
      timeout: 10000,
    })

    await openJobCostingTab(page, jobUrl, 'quote')
    await autoId(page, 'JobQuoteTab-copy-from-estimate').click()

    await expect(page.getByText('Estimate copied to quote.')).toBeVisible({ timeout: 10000 })
    // The seed is blank, so the replace asked nothing.
    await expect(page.getByText('Replace this quote?')).toBeHidden()
    await waitForCostLineRow(page, 'Straightening charge')
  })

  test('a priced quote asks first; archive-and-replace brings the new line over', async ({
    authenticatedPage: page,
  }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')
    await addAdjustmentCostLine(page, 'Estimate Details', 'Extra bracing', '2', '50')

    await openJobCostingTab(page, jobUrl, 'quote')
    await autoId(page, 'JobQuoteTab-copy-from-estimate').click()

    await expect(page.getByText('Replace this quote?')).toBeVisible({ timeout: 10000 })
    await autoId(page, 'JobQuoteTab-archive-and-replace').click()

    await expect(page.getByText('Estimate copied to quote.')).toBeVisible({ timeout: 10000 })
    await waitForCostLineRow(page, 'Extra bracing')
    await waitForCostLineRow(page, 'Straightening charge')

    // The archived quote stays visible: the Revisions history holds what the
    // replace displaced, including the line it archived.
    await autoId(page, 'JobQuoteTab-revisions').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Quote Revisions History')).toBeVisible({ timeout: 10000 })
    // Scoped to the dialog: the tab header also says "Revision 1" (the live
    // CostSet rev), which is a different number than the archive's.
    await expect(dialog.getByText('Revision 1')).toBeVisible()
    await expect(dialog.getByText('Straightening charge')).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test('a double press answers as a no-op instead of stacking an archive', async ({
    authenticatedPage: page,
  }) => {
    await openJobCostingTab(page, jobUrl, 'quote')
    await autoId(page, 'JobQuoteTab-copy-from-estimate').click()

    await expect(page.getByText('The quote already matches the estimate.')).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByText('Replace this quote?')).toBeHidden()
  })

  test('the Actual tab carries the same summary panel (KAN-349)', async ({
    authenticatedPage: page,
  }) => {
    await openJobCostingTab(page, jobUrl, 'actual')

    const summaryPanel = autoId(page, 'JobActualTab-summary')
    await expect(summaryPanel).toBeVisible({ timeout: 10000 })
    await expect(summaryPanel).toContainText('Actual Summary')
    // Nothing has been booked to actuals: the server answers $0.00, and the
    // panel must render that answer rather than a loading or error state.
    await expect(summaryPanel).toContainText('$0.00')
  })
})
