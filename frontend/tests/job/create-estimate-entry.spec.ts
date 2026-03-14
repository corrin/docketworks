import { test, expect } from '../fixtures/auth'
import type { Page, Locator } from '@playwright/test'
import { autoId, waitForAutosave, createTestJob } from '../fixtures/helpers'

/**
 * Tests for estimate operations on the Estimate tab.
 * All tests share ONE job and run serially.
 */

// ============================================================================
// Helper Functions
// ============================================================================

/** Iterate over cost line rows and return matches based on description */
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

async function findRowIndexByDescription(page: Page, description: string): Promise<number> {
  const { indices } = await findRowsByDescription(page, description)
  return indices[0] ?? -1
}

async function navigateToEstimateTab(page: Page, jobUrl: string): Promise<void> {
  await page.goto(jobUrl)
  await page.waitForLoadState('networkidle')
  await autoId(page, 'JobViewTabs-estimate').click()
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(2000)
}

async function clickAddRow(page: Page): Promise<void> {
  await autoId(page, 'SmartCostLinesTable-add-row').waitFor({ timeout: 10000 })
  await autoId(page, 'SmartCostLinesTable-add-row').click()
}

async function addAdjustmentEntry(
  page: Page,
  description: string,
  quantity: string,
  unitCost: string,
  unitRev: string,
): Promise<void> {
  await clickAddRow(page)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  const rows = page.locator('[data-automation-id^="DataTable-row-"]')
  const newRow = rows.last()

  const descInput = newRow.locator('textarea').first()
  await descInput.click()
  await descInput.fill(description)
  await page.keyboard.press('Tab')

  await page.keyboard.type(quantity)
  await page.keyboard.press('Tab')

  await page.keyboard.type(unitCost)
  await page.keyboard.press('Tab')

  await page.keyboard.type(unitRev)
  await page.keyboard.press('Tab')

  await waitForAutosave(page)
}

// ============================================================================
// Test Suite: Estimate Operations (all tests share ONE job)
// ============================================================================

test.describe.serial('estimate operations', () => {
  let jobUrl: string

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()

    // Login
    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD
    await page.goto('/login')
    await page.locator('#username').fill(username!)
    await page.locator('#password').fill(password!)
    await page.getByRole('button', { name: 'Sign In' }).click()
    await page.waitForURL('**/kanban')

    // Create ONE job for all tests
    jobUrl = await createTestJob(page, 'Estimate')
    console.log(`Created job at: ${jobUrl}`)

    await context.close()
  })

  test('add Labour entry', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    await clickAddRow(page)

    const labourOption = autoId(page, 'ItemSelect-option-labour')
    await labourOption.waitFor({ timeout: 10000 })
    await labourOption.click()

    await page.waitForTimeout(1000)

    const labourRow = await findRowByDescription(page, 'Labour')
    expect(labourRow).not.toBeNull()

    await labourRow!.click()
    const qtyInput = labourRow!.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('2')
    await page.keyboard.press('Tab')

    await waitForAutosave(page)

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const labourRowAfter = await findRowByDescription(page, 'Labour')
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
    await wingNutOption.click()

    await page.waitForTimeout(2000)

    const materialRow = await findRowByDescription(page, 'M8 ZINC WING NUT')
    expect(materialRow).not.toBeNull()

    const qtyInput = materialRow!.locator('input').first()
    await qtyInput.click()
    await qtyInput.fill('10')
    await page.keyboard.press('Tab')

    await waitForAutosave(page)

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const materialRowAfter = await findRowByDescription(page, 'M8 ZINC WING NUT')
    expect(materialRowAfter).not.toBeNull()
  })

  test('add Adjustment entry', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    await addAdjustmentEntry(page, 'Discount - repeat customer', '1', '-50', '-50')

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    const adjustmentRow = await findRowByDescription(page, 'Discount - repeat customer')
    expect(adjustmentRow).not.toBeNull()
  })

  test('verify all entries persist', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    const labourRow = await findRowByDescription(page, 'Labour')
    const materialRow = await findRowByDescription(page, 'M8 ZINC WING NUT')
    const adjustmentRow = await findRowByDescription(page, 'Discount - repeat customer')

    expect(labourRow).not.toBeNull()
    expect(materialRow).not.toBeNull()
    expect(adjustmentRow).not.toBeNull()

    console.log('All 3 entry types verified')
  })

  test('edit quantity and unit cost', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    // Add a new adjustment for editing tests
    await addAdjustmentEntry(page, 'Test Adjustment for Editing', '1', '10', '10')

    const rowIndex = await findRowIndexByDescription(page, 'Test Adjustment for Editing')
    expect(rowIndex).toBeGreaterThanOrEqual(0)

    // Change quantity to 3
    const qtyInput = autoId(page, `SmartCostLinesTable-quantity-${rowIndex}`)
    await qtyInput.dblclick()
    await page.keyboard.type('3')
    await page.keyboard.press('Tab')

    // Change unit cost to 25
    const unitCostInput = autoId(page, `SmartCostLinesTable-unit-cost-${rowIndex}`)
    await unitCostInput.dblclick()
    await page.keyboard.type('25')
    await page.keyboard.press('Tab')

    await waitForAutosave(page)

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
    await page.keyboard.press('Tab')

    // Verify unit cost unchanged
    const currentUnitCost = await unitCostInput.inputValue()
    expect(currentUnitCost).toBe(originalUnitCost)

    await waitForAutosave(page)

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
    console.log(`M8 ZINC rows before: ${m8IndicesBefore.length}`)
    expect(m8IndicesBefore.length).toBeGreaterThan(0)

    const materialRowIndex = m8IndicesBefore[0]

    // Click the item cell button to open selector
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
    await newItemOption.click()

    await waitForAutosave(page)

    // Verify persistence
    await navigateToEstimateTab(page, jobUrl)

    // Count M8 ZINC rows after - should be one less
    const { indices: m8IndicesAfter } = await findRowsByDescription(page, 'M8 ZINC WING NUT')
    console.log(`M8 ZINC rows after: ${m8IndicesAfter.length}`)
    expect(m8IndicesAfter.length).toBe(m8IndicesBefore.length - 1)

    // Check for M10 row using the helper with 'includes' matcher
    const { rows: m10Rows } = await findRowsByDescription(page, 'M10', 'includes')
    expect(m10Rows.length).toBeGreaterThan(0)
  })

  test('delete costline', async ({ authenticatedPage: page }) => {
    await navigateToEstimateTab(page, jobUrl)

    // Add a row specifically for deletion
    await addAdjustmentEntry(page, 'Row to be deleted', '1', '100', '100')

    const rowsBefore = await page.locator('[data-automation-id^="DataTable-row-"]').count()
    const deleteRowIndex = await findRowIndexByDescription(page, 'Row to be deleted')
    expect(deleteRowIndex).toBeGreaterThanOrEqual(0)

    // Set up dialog handler and click delete
    page.on('dialog', (dialog) => dialog.accept())

    const deleteButton = autoId(page, `SmartCostLinesTable-delete-${deleteRowIndex}`)
    await deleteButton.click()

    await waitForAutosave(page)

    // Verify deletion persisted
    await navigateToEstimateTab(page, jobUrl)

    const deletedRow = await findRowByDescription(page, 'Row to be deleted')
    expect(deletedRow).toBeNull()

    const rowsAfter = await page.locator('[data-automation-id^="DataTable-row-"]').count()
    expect(rowsAfter).toBeLessThan(rowsBefore)
  })
})
