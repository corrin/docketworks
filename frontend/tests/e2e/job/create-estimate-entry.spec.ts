import type { Page, Locator } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, waitForAutosave } from '../helpers'

/**
 * Estimate operations on the Estimate tab. All tests share ONE job and run
 * serially (each later test asserts on rows earlier tests created).
 *
 * Port deviations from v1, each deliberate:
 * - The shared job is created by the first serial test through the standard
 *   authenticated fixture, not a hand-rolled beforeAll login.
 * - waitForAutosave is armed BEFORE the action that leaves the row: creation
 *   fires on row exit (same rule as v1), and the derived unit revenue means
 *   the exit gesture is a click on the section heading rather than v1's
 *   custom Tab-to-next-row handler.
 */

interface RowMatch {
  row: Locator
  /** The row's position in the table, which the SmartCostLinesTable
      automation ids are keyed on. */
  index: number
}

/**
 * One pass over the rows. Descriptions live in textareas, so a row's
 * description is not matchable as row text.
 *
 * A detached read throws rather than reading as an empty description: a row
 * that vanished mid-scan is a scan to retry, and swallowing it as `''` made
 * it indistinguishable from a row whose description really is blank — which
 * is how the caller below came back with "no such row" and no retry.
 */
async function findRowsByDescription(
  page: Page,
  description: string,
  matcher: 'exact' | 'includes' = 'exact',
): Promise<RowMatch[]> {
  const allRows = page.locator('[data-automation-id^="DataTable-row-"]')
  const rowCount = await allRows.count()
  const matches: RowMatch[] = []

  for (let i = 0; i < rowCount; i++) {
    const row = allRows.nth(i)
    const value = await row.locator('textarea').first().inputValue()
    const matched = matcher === 'exact' ? value === description : value.includes(description)
    if (matched) {
      matches.push({ row, index: i })
    }
  }
  return matches
}

/** One pass, for the callers asserting a row is NOT there. */
async function findRowByDescription(page: Page, description: string): Promise<Locator | null> {
  const [first] = await findRowsByDescription(page, description)
  return first === undefined ? null : first.row
}

/**
 * Every matching row, retried until at least one matches.
 *
 * Every caller asserting presence goes through here, because the scan above
 * is imperative: it reads rows one at a time while a settled cost-line write
 * is followed by TWO refetches within about 80ms — the cost set, and the job
 * itself (invalidateJobViews, because a cost-line write moves the job's
 * ETag). A single pass can therefore read the table between frames and miss a
 * row that is there, which is what failed this file once in a full sweep and
 * passed eight times in isolation. Filtering a locator by its input value is
 * not expressible, so polling the scan is the honest form; v1 hid the same
 * race behind waitForTimeout sleeps.
 */
async function waitForRowsByDescription(
  page: Page,
  description: string,
  matcher: 'exact' | 'includes' = 'exact',
): Promise<RowMatch[]> {
  const found: RowMatch[] = []
  await expect(async () => {
    const matches = await findRowsByDescription(page, description, matcher)
    found.length = 0
    found.push(...matches)
    expect(found.length, `no row described "${description}"`).toBeGreaterThan(0)
  }).toPass({ timeout: 10000 })
  return found
}

/** The first matching row, retried until it appears. */
async function waitForRowByDescription(page: Page, description: string): Promise<RowMatch> {
  const [first] = await waitForRowsByDescription(page, description)
  if (first === undefined) {
    throw new Error(`Row "${description}" vanished after the scan that found it`)
  }
  return first
}

async function findRowIndexByDescription(page: Page, description: string): Promise<number> {
  const { index } = await waitForRowByDescription(page, description)
  return index
}

async function navigateToEstimateTab(page: Page, jobUrl: string): Promise<void> {
  if (!jobUrl) {
    throw new Error(
      'Serial suite: the shared job is created by the first test — run the whole file, not a grep of a later test.',
    )
  }
  await page.goto(jobUrl)
  await page.waitForLoadState('networkidle')
  const tab = autoId(page, 'JobViewTabs-estimate')
  await tab.waitFor({ state: 'visible' })
  await tab.click()
  await page.waitForLoadState('networkidle')
  await page.locator('[data-row-id]').last().waitFor({ state: 'visible', timeout: 3000 })
}

/** Leave the focused row so a completed draft POSTs (row-exit persistence). */
async function exitRow(page: Page): Promise<void> {
  await page.getByRole('heading', { name: 'Estimate Details' }).click()
}

async function clickAddRow(page: Page): Promise<string> {
  const selectItemButton = page.getByRole('button', { name: 'Select Item' }).last()
  await selectItemButton.waitFor({ timeout: 10000 })
  const row = selectItemButton.locator('xpath=ancestor::*[@data-row-id][1]')
  const rowId = await row.getAttribute('data-row-id')
  if (!rowId) throw new Error('Could not find phantom row')
  await selectItemButton.click()
  return rowId
}

function getRowById(page: Page, rowId: string): Locator {
  return page.locator(`[data-row-id="${rowId}"]`)
}

async function addAdjustmentEntry(
  page: Page,
  description: string,
  quantity: string,
  unitCost: string,
): Promise<void> {
  const rowId = await clickAddRow(page)
  await page.keyboard.press('Escape')

  const newRow = getRowById(page, rowId)

  const descInput = newRow.locator('textarea').first()
  const quantityInput = newRow.locator('[data-automation-id^="SmartCostLinesTable-quantity-"]')
  const unitCostInput = newRow.locator('[data-automation-id^="SmartCostLinesTable-unit-cost-"]')
  const unitRevenueInput = newRow.locator('[data-automation-id^="SmartCostLinesTable-unit-rev-"]')

  await descInput.click()
  await descInput.fill(description)
  await page.keyboard.press('Tab')
  await expect(quantityInput).toBeFocused()

  await quantityInput.fill(quantity)
  await page.keyboard.press('Tab')
  await expect(unitCostInput).toBeFocused()

  await unitCostInput.fill(unitCost)
  await page.keyboard.press('Tab')
  await expect(unitRevenueInput).toBeFocused()

  // Creation happens only when focus leaves the complete row, so rapid edits
  // to Unit Revenue cannot be overwritten by an earlier POST response.
  const savePromise = waitForAutosave(page)
  await exitRow(page)
  await savePromise
}

test.describe.serial('estimate operations', () => {
  test.setTimeout(120000)

  let jobUrl: string

  test('create the shared job and add a Labour entry', async ({ authenticatedPage: page }) => {
    jobUrl = await createTestJob(page, 'Estimate')

    await navigateToEstimateTab(page, jobUrl)

    await clickAddRow(page)

    // One labour option per subtype; pick the Workshop one.
    const labourOption = page
      .locator('[data-automation-id^="ItemSelect-option-labour"]')
      .filter({ hasText: 'Workshop' })
    await labourOption.waitFor({ timeout: 10000 })
    // A labour pick completes the line, so it persists immediately.
    const pickSave = waitForAutosave(page)
    await labourOption.click()
    await pickSave

    const { row: labourRow } = await waitForRowByDescription(page, 'Workshop')

    const qtyInput = labourRow.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('2')
    const editSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await editSave

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    await waitForRowByDescription(page, 'Workshop')
  })

  test('add Material entry', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    await clickAddRow(page)

    const searchInput = page.getByPlaceholder('Search items by description, code, or type...')
    await searchInput.waitFor({ timeout: 10000 })
    await searchInput.click()
    await searchInput.fill('M8 ZINC')

    const wingNutOption = page
      .locator('[data-automation-id^="ItemSelect-option-"]')
      .filter({ hasText: 'M8 ZINC WING NUT' })
    await wingNutOption.waitFor({ timeout: 10000 })
    const pickSave = waitForAutosave(page)
    await wingNutOption.click()
    await pickSave

    const { row: materialRow } = await waitForRowByDescription(page, 'M8 ZINC WING NUT')

    const qtyInput = materialRow.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('10')
    const editSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await editSave

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    await waitForRowByDescription(page, 'M8 ZINC WING NUT')
  })

  test('add Adjustment entry', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    await addAdjustmentEntry(page, 'Discount - repeat customer', '1', '-50')

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    await waitForRowByDescription(page, 'Discount - repeat customer')
  })

  test('verify all entries persist', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    // Each throws if its row never appears, and retries while the tab's two
    // refetches settle.
    await waitForRowByDescription(page, 'Workshop')
    await waitForRowByDescription(page, 'M8 ZINC WING NUT')
    await waitForRowByDescription(page, 'Discount - repeat customer')
  })

  test('edit quantity and unit cost', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    // Add a new adjustment for editing tests
    await addAdjustmentEntry(page, 'Test Adjustment for Editing', '1', '10')

    const rowIndex = await findRowIndexByDescription(page, 'Test Adjustment for Editing')
    expect(rowIndex).toBeGreaterThanOrEqual(0)

    // Change quantity to 3
    const qtyInput = autoId(page, `SmartCostLinesTable-quantity-${rowIndex}`)
    await qtyInput.click()
    await qtyInput.fill('3')
    const qtySave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await qtySave

    // Change unit cost to 25
    const unitCostInput = autoId(page, `SmartCostLinesTable-unit-cost-${rowIndex}`)
    await unitCostInput.click()
    await unitCostInput.fill('25')
    const costSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await costSave

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const newRowIndex = await findRowIndexByDescription(page, 'Test Adjustment for Editing')
    expect(newRowIndex).toBeGreaterThanOrEqual(0)

    await expect(autoId(page, `SmartCostLinesTable-quantity-${newRowIndex}`)).toHaveValue('3')
    await expect(autoId(page, `SmartCostLinesTable-unit-cost-${newRowIndex}`)).toHaveValue('25')
  })

  test('override unit revenue', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    const rowIndex = await findRowIndexByDescription(page, 'Test Adjustment for Editing')
    expect(rowIndex).toBeGreaterThanOrEqual(0)

    const unitCostInput = autoId(page, `SmartCostLinesTable-unit-cost-${rowIndex}`)
    const originalUnitCost = await unitCostInput.inputValue()

    // Change unit revenue to 99
    const unitRevInput = autoId(page, `SmartCostLinesTable-unit-rev-${rowIndex}`)
    await unitRevInput.click()
    await unitRevInput.fill('99')
    const revSave = waitForAutosave(page)
    await page.keyboard.press('Tab')

    // Verify unit cost unchanged
    const currentUnitCost = await unitCostInput.inputValue()
    expect(currentUnitCost).toBe(originalUnitCost)

    await revSave

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const newRowIndex = await findRowIndexByDescription(page, 'Test Adjustment for Editing')
    await expect(autoId(page, `SmartCostLinesTable-unit-rev-${newRowIndex}`)).toHaveValue('99')
    await expect(autoId(page, `SmartCostLinesTable-unit-cost-${newRowIndex}`)).toHaveValue(
      originalUnitCost,
    )
  })

  test('change material code', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    // Count M8 ZINC rows before change, from the same settled scan that
    // located the row: a second, non-retrying scan here could see a refetch
    // mid-flight and undercount despite the row being on screen throughout.
    const m8Before = await waitForRowsByDescription(page, 'M8 ZINC WING NUT')
    const [firstM8] = m8Before
    if (firstM8 === undefined) {
      throw new Error('Row "M8 ZINC WING NUT" vanished after the scan that found it')
    }
    const materialRowIndex = firstM8.index

    // Click the item cell button to open the selector
    const itemCell = autoId(page, `SmartCostLinesTable-item-${materialRowIndex}`)
    const itemButton = itemCell.locator('button')
    await itemButton.click()

    const searchInput = page.getByPlaceholder('Search items by description, code, or type...')
    await searchInput.waitFor({ timeout: 10000 })
    await searchInput.click()
    await searchInput.fill('M10')

    const newItemOption = page
      .locator('[data-automation-id^="ItemSelect-option-"]')
      .filter({ hasText: 'M10' })
      .first()
    await newItemOption.waitFor({ timeout: 10000 })
    const pickSave = waitForAutosave(page)
    await newItemOption.click()
    await pickSave

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    // Count M8 ZINC rows after - should be one less
    const m8After = await findRowsByDescription(page, 'M8 ZINC WING NUT')
    expect(m8After.length).toBe(m8Before.length - 1)

    // Check for an M10 row using the helper with 'includes' matcher
    await waitForRowsByDescription(page, 'M10', 'includes')
  })

  test('delete costline', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    // Add a row specifically for deletion
    await addAdjustmentEntry(page, 'Row to be deleted', '1', '100')

    const rowsBefore = await page.locator('[data-automation-id^="DataTable-row-"]').count()
    const deleteRowIndex = await findRowIndexByDescription(page, 'Row to be deleted')
    expect(deleteRowIndex).toBeGreaterThanOrEqual(0)

    // Accept the confirm dialog and delete
    page.on('dialog', (dialog) => void dialog.accept())

    const deleteButton = autoId(page, `SmartCostLinesTable-delete-${deleteRowIndex}`)
    const deleteSave = waitForAutosave(page)
    await deleteButton.click()
    await deleteSave

    // Verify deletion persisted
    await navigateToEstimateTab(page, jobUrl)

    const deletedRow = await findRowByDescription(page, 'Row to be deleted')
    expect(deletedRow).toBeNull()

    const rowsAfter = await page.locator('[data-automation-id^="DataTable-row-"]').count()
    expect(rowsAfter).toBeLessThan(rowsBefore)
  })
})
