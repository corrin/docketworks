import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, waitForAutosave } from '../helpers'

/**
 * Copy from Estimate on the Quote tab (KAN-346). One shared fixed-price job,
 * serial: each test builds on the quote state the previous one left.
 *
 * The three server answers, each exercised through the UI:
 * - blank quote (the $0 creation seed) → copied silently, no dialog;
 * - priced quote → the archive-and-replace dialog, confirmed;
 * - quote already matching the estimate → a no-op answer, so a double press
 *   never stacks a second identical archive.
 */

async function openTab(
  page: Page,
  jobUrl: string,
  tab: 'estimate' | 'quote' | 'actual',
): Promise<void> {
  if (!jobUrl) {
    throw new Error(
      'Serial suite: the shared job is created by the first test — run the whole file, not a grep of a later test.',
    )
  }
  await page.goto(jobUrl)
  await page.waitForLoadState('networkidle')
  const tabButton = autoId(page, `JobViewTabs-${tab}`)
  await tabButton.waitFor({ state: 'visible' })
  await tabButton.click()
  await page.waitForLoadState('networkidle')
  if (tab !== 'actual') {
    // Estimate and quote grids always render at least the phantom row; the
    // actual grid can be legitimately empty, so its ready signal is the
    // summary panel instead (asserted by the caller).
    await page.locator('[data-row-id]').last().waitFor({ state: 'visible', timeout: 3000 })
  }
}

/**
 * Row descriptions live in textareas, so they are not matchable as row text;
 * the scan is polled because a settled cost-line write triggers refetches
 * that can catch a single pass between frames (same reasoning as the
 * create-estimate-entry spec's scan).
 */
async function waitForRowWithDescription(page: Page, description: string): Promise<void> {
  await expect(async () => {
    await page.waitForLoadState('networkidle')
    const rows = page.locator('[data-automation-id^="DataTable-row-"]')
    const count = await rows.count()
    const values: string[] = []
    for (let i = 0; i < count; i++) {
      values.push(await rows.nth(i).locator('textarea').first().inputValue())
    }
    expect(values, `no row described "${description}"`).toContain(description)
  }).toPass({ timeout: 10000 })
}

/** Add a completed adjustment line on the Estimate tab (persists on row exit). */
async function addEstimateAdjustment(
  page: Page,
  description: string,
  quantity: string,
  unitCost: string,
): Promise<void> {
  const selectItemButton = page.getByRole('button', { name: 'Select Item' }).last()
  await selectItemButton.waitFor({ timeout: 10000 })
  const row = selectItemButton.locator('xpath=ancestor::*[@data-row-id][1]')
  const rowId = await row.getAttribute('data-row-id')
  if (!rowId) throw new Error('Could not find phantom row')
  await selectItemButton.click()
  await page.keyboard.press('Escape')

  const newRow = page.locator(`[data-row-id="${rowId}"]`)
  await newRow.locator('textarea').first().fill(description)
  await newRow.locator('[data-automation-id^="SmartCostLinesTable-quantity-"]').fill(quantity)
  await newRow.locator('[data-automation-id^="SmartCostLinesTable-unit-cost-"]').fill(unitCost)

  const savePromise = waitForAutosave(page)
  await page.getByRole('heading', { name: 'Estimate Details' }).click()
  await savePromise
}

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

    await openTab(page, jobUrl, 'estimate')
    await addEstimateAdjustment(page, 'Straightening charge', '1', '100')

    // KAN-349: the Estimate tab shows the server-owned summary — the $100
    // adjustment cost must land in it (revenue derivation is unit-tested).
    await expect(autoId(page, 'JobEstimateTab-summary')).toContainText('$100.00', {
      timeout: 10000,
    })

    await openTab(page, jobUrl, 'quote')
    await autoId(page, 'JobQuoteTab-copy-from-estimate').click()

    await expect(page.getByText('Estimate copied to quote.')).toBeVisible({ timeout: 10000 })
    // The seed is blank, so the replace asked nothing.
    await expect(page.getByText('Replace this quote?')).toBeHidden()
    await waitForRowWithDescription(page, 'Straightening charge')
  })

  test('a priced quote asks first; archive-and-replace brings the new line over', async ({
    authenticatedPage: page,
  }) => {
    await openTab(page, jobUrl, 'estimate')
    await addEstimateAdjustment(page, 'Extra bracing', '2', '50')

    await openTab(page, jobUrl, 'quote')
    await autoId(page, 'JobQuoteTab-copy-from-estimate').click()

    await expect(page.getByText('Replace this quote?')).toBeVisible({ timeout: 10000 })
    await autoId(page, 'JobQuoteTab-archive-and-replace').click()

    await expect(page.getByText('Estimate copied to quote.')).toBeVisible({ timeout: 10000 })
    await waitForRowWithDescription(page, 'Extra bracing')
    await waitForRowWithDescription(page, 'Straightening charge')

    // The archived quote stays visible: the Revisions history holds what the
    // replace displaced, including the line it archived.
    await autoId(page, 'JobQuoteTab-revisions').click()
    await expect(page.getByText('Quote Revisions History')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('Revision 1')).toBeVisible()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Straightening charge')).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test('a double press answers as a no-op instead of stacking an archive', async ({
    authenticatedPage: page,
  }) => {
    await openTab(page, jobUrl, 'quote')
    await autoId(page, 'JobQuoteTab-copy-from-estimate').click()

    await expect(page.getByText('The quote already matches the estimate.')).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByText('Replace this quote?')).toBeHidden()
  })

  test('the Actual tab carries the same summary panel (KAN-349)', async ({
    authenticatedPage: page,
  }) => {
    await openTab(page, jobUrl, 'actual')

    const summaryPanel = autoId(page, 'JobActualTab-summary')
    await expect(summaryPanel).toBeVisible({ timeout: 10000 })
    await expect(summaryPanel).toContainText('Actual Summary')
    // Nothing has been booked to actuals: the server answers $0.00, and the
    // panel must render that answer rather than a loading or error state.
    await expect(summaryPanel).toContainText('$0.00')
  })
})
