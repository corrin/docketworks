import type { Page, Locator } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import {
  autoId,
  clickAddCostLineRow,
  createTestJob,
  findCostLineRows,
  openJobCostingTab,
  waitForAutosave,
  waitForCostLineRow,
  waitForCostLineRows,
} from '../helpers'

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

/** This spec's callers assert a row is NOT there, so absence is a null. */
async function findRowByDescription(page: Page, description: string): Promise<Locator | null> {
  const [first] = await findCostLineRows(page, description)
  return first === undefined ? null : first.row
}

/** The row described, addressed by id (see findCostLineRows on why never by position). */
async function rowByDescription(page: Page, description: string): Promise<Locator> {
  const { row } = await waitForCostLineRow(page, description)
  return row
}

function cellInput(row: Locator, field: 'quantity' | 'unit-cost' | 'unit-rev'): Locator {
  return row.locator(`[data-automation-id^="SmartCostLinesTable-${field}-"]`)
}

/** Leave the focused row so a completed draft POSTs (row-exit persistence). */
async function exitRow(page: Page): Promise<void> {
  await page.getByRole('heading', { name: 'Estimate Details' }).click()
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
  const rowId = await clickAddCostLineRow(page)
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

    await openJobCostingTab(page, jobUrl, 'estimate')

    await clickAddCostLineRow(page)

    // One labour option per subtype; pick the Workshop one.
    const labourOption = page
      .locator('[data-automation-id^="ItemSelect-option-labour"]')
      .filter({ hasText: 'Workshop' })
    await labourOption.waitFor({ timeout: 10000 })
    // A labour pick completes the line, so it persists immediately.
    const pickSave = waitForAutosave(page)
    await labourOption.click()
    await pickSave

    const { row: labourRow } = await waitForCostLineRow(page, 'Workshop')

    const qtyInput = labourRow.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('2')
    const editSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await editSave

    // Verify persistence
    await openJobCostingTab(page, jobUrl, 'estimate')

    await waitForCostLineRow(page, 'Workshop')
  })

  test('add Material entry', async ({ authenticatedPage: page }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')

    await clickAddCostLineRow(page)

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

    const { row: materialRow } = await waitForCostLineRow(page, 'M8 ZINC WING NUT')

    const qtyInput = materialRow.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('10')
    const editSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await editSave

    // Verify persistence
    await openJobCostingTab(page, jobUrl, 'estimate')

    await waitForCostLineRow(page, 'M8 ZINC WING NUT')
  })

  test('add Adjustment entry', async ({ authenticatedPage: page }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')

    await addAdjustmentEntry(page, 'Discount - repeat customer', '1', '-50')

    // Verify persistence
    await openJobCostingTab(page, jobUrl, 'estimate')

    await waitForCostLineRow(page, 'Discount - repeat customer')
  })

  test('verify all entries persist', async ({ authenticatedPage: page }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')

    // Each throws if its row never appears, and retries while the tab's two
    // refetches settle.
    await waitForCostLineRow(page, 'Workshop')
    await waitForCostLineRow(page, 'M8 ZINC WING NUT')
    await waitForCostLineRow(page, 'Discount - repeat customer')
  })

  test('edit quantity and unit cost', async ({ authenticatedPage: page }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')

    // Add a new adjustment for editing tests
    await addAdjustmentEntry(page, 'Test Adjustment for Editing', '1', '10')

    const row = await rowByDescription(page, 'Test Adjustment for Editing')

    // Change quantity to 3
    const qtyInput = cellInput(row, 'quantity')
    await qtyInput.click()
    await qtyInput.fill('3')
    const qtySave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await qtySave

    // Change unit cost to 25
    const unitCostInput = cellInput(row, 'unit-cost')
    await unitCostInput.click()
    await unitCostInput.fill('25')
    const costSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await costSave

    // Verify persistence
    await openJobCostingTab(page, jobUrl, 'estimate')

    const reloaded = await rowByDescription(page, 'Test Adjustment for Editing')

    await expect(cellInput(reloaded, 'quantity')).toHaveValue('3')
    await expect(cellInput(reloaded, 'unit-cost')).toHaveValue('25')
  })

  test('override unit revenue', async ({ authenticatedPage: page }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')

    const row = await rowByDescription(page, 'Test Adjustment for Editing')

    const unitCostInput = cellInput(row, 'unit-cost')
    const originalUnitCost = await unitCostInput.inputValue()

    // Change unit revenue to 99
    const unitRevInput = cellInput(row, 'unit-rev')
    await unitRevInput.click()
    await unitRevInput.fill('99')
    const revSave = waitForAutosave(page)
    await page.keyboard.press('Tab')

    // Verify unit cost unchanged
    const currentUnitCost = await unitCostInput.inputValue()
    expect(currentUnitCost).toBe(originalUnitCost)

    await revSave

    // Verify persistence
    await openJobCostingTab(page, jobUrl, 'estimate')

    const reloaded = await rowByDescription(page, 'Test Adjustment for Editing')
    await expect(cellInput(reloaded, 'unit-rev')).toHaveValue('99')
    await expect(cellInput(reloaded, 'unit-cost')).toHaveValue(originalUnitCost)
  })

  test('change material code', async ({ authenticatedPage: page }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')

    // Count M8 ZINC rows before change, from the same settled scan that
    // located the row: a second, non-retrying scan here could see a refetch
    // mid-flight and undercount despite the row being on screen throughout.
    const m8Before = await waitForCostLineRows(page, 'M8 ZINC WING NUT')
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
    await openJobCostingTab(page, jobUrl, 'estimate')

    // Count M8 ZINC rows after - should be one less
    const m8After = await findCostLineRows(page, 'M8 ZINC WING NUT')
    expect(m8After.length).toBe(m8Before.length - 1)

    // Check for an M10 row using the helper with 'includes' matcher
    await waitForCostLineRows(page, 'M10', 'includes')
  })

  test('delete costline', async ({ authenticatedPage: page }) => {
    await openJobCostingTab(page, jobUrl, 'estimate')

    // Add a row specifically for deletion
    await addAdjustmentEntry(page, 'Row to be deleted', '1', '100')

    const rowsBefore = await page.locator('[data-automation-id^="DataTable-row-"]').count()
    const doomed = await rowByDescription(page, 'Row to be deleted')

    // Accept the confirm dialog and delete
    page.on('dialog', (dialog) => void dialog.accept())

    const deleteButton = doomed.locator('[data-automation-id^="SmartCostLinesTable-delete-"]')
    const deleteSave = waitForAutosave(page)
    await deleteButton.click()
    await deleteSave

    // Verify deletion persisted
    await openJobCostingTab(page, jobUrl, 'estimate')

    const deletedRow = await findRowByDescription(page, 'Row to be deleted')
    expect(deletedRow).toBeNull()

    const rowsAfter = await page.locator('[data-automation-id^="DataTable-row-"]').count()
    expect(rowsAfter).toBeLessThan(rowsBefore)
  })
})
