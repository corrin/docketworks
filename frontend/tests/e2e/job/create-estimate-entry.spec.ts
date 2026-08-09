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

async function findRowsByDescription(
  page: Page,
  description: string,
  matcher: 'exact' | 'includes' = 'exact',
): Promise<{ rows: Locator[]; indices: number[] }> {
  const allRows = page.locator('[data-automation-id^="DataTable-row-"]')
  const rowCount = await allRows.count()
  const rows: Locator[] = []
  const indices: number[] = []

  for (let i = 0; i < rowCount; i++) {
    const row = allRows.nth(i)
    const textarea = row.locator('textarea').first()
    const value = await textarea.inputValue().catch(() => '')
    const matches = matcher === 'exact' ? value === description : value.includes(description)
    if (matches) {
      rows.push(row)
      indices.push(i)
    }
  }
  return { rows, indices }
}

async function findRowByDescription(page: Page, description: string): Promise<Locator | null> {
  const { rows } = await findRowsByDescription(page, description)
  return rows[0] ?? null
}

/** Retry the description scan: a just-created line swaps its draft row for a
 * server row mid-render, and a single pass can read rows between frames
 * (v1 hid the same race behind waitForTimeout sleeps). */
async function waitForRowByDescription(page: Page, description: string): Promise<Locator> {
  await expect(async () => {
    const row = await findRowByDescription(page, description)
    expect(row).not.toBeNull()
  }).toPass({ timeout: 10000 })
  const row = await findRowByDescription(page, description)
  if (!row) throw new Error(`Row "${description}" vanished after appearing`)
  return row
}

async function findRowIndexByDescription(page: Page, description: string): Promise<number> {
  const { indices } = await findRowsByDescription(page, description)
  return indices[0] ?? -1
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

    const labourRow = await waitForRowByDescription(page, 'Workshop')

    const qtyInput = labourRow.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('2')
    const editSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await editSave

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const labourRowAfter = await findRowByDescription(page, 'Workshop')
    expect(labourRowAfter).not.toBeNull()
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

    const materialRow = await waitForRowByDescription(page, 'M8 ZINC WING NUT')

    const qtyInput = materialRow.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('10')
    const editSave = waitForAutosave(page)
    await page.keyboard.press('Tab')
    await editSave

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const materialRowAfter = await findRowByDescription(page, 'M8 ZINC WING NUT')
    expect(materialRowAfter).not.toBeNull()
  })

  test('add Adjustment entry', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    await addAdjustmentEntry(page, 'Discount - repeat customer', '1', '-50')

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const adjustmentRow = await findRowByDescription(page, 'Discount - repeat customer')
    expect(adjustmentRow).not.toBeNull()
  })

  test('verify all entries persist', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    const labourRow = await findRowByDescription(page, 'Workshop')
    const materialRow = await findRowByDescription(page, 'M8 ZINC WING NUT')
    const adjustmentRow = await findRowByDescription(page, 'Discount - repeat customer')

    expect(labourRow).not.toBeNull()
    expect(materialRow).not.toBeNull()
    expect(adjustmentRow).not.toBeNull()
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

    // Count M8 ZINC rows before change
    const { indices: m8IndicesBefore } = await findRowsByDescription(page, 'M8 ZINC WING NUT')
    expect(m8IndicesBefore.length).toBeGreaterThan(0)

    const materialRowIndex = m8IndicesBefore[0]

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
    const { indices: m8IndicesAfter } = await findRowsByDescription(page, 'M8 ZINC WING NUT')
    expect(m8IndicesAfter.length).toBe(m8IndicesBefore.length - 1)

    // Check for an M10 row using the helper with 'includes' matcher
    const { rows: m10Rows } = await findRowsByDescription(page, 'M10', 'includes')
    expect(m10Rows.length).toBeGreaterThan(0)
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
