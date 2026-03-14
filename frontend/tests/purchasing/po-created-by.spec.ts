import { test, expect } from '../fixtures/auth'
import { autoId, createTestPurchaseOrder } from '../fixtures/helpers'

/**
 * Tests for purchase order "Created By" display.
 * Verifies the Created By field appears on list and detail screens.
 */

test.describe('purchase order created by', () => {
  test('displays created by on list and detail screens', async ({ authenticatedPage: page }) => {
    // Create a purchase order
    const poUrl = await createTestPurchaseOrder(page)
    console.log(`Created PO at: ${poUrl}`)

    // Extract PO ID from URL
    const poId = poUrl.split('/').pop()

    // Navigate to PO list
    await page.goto('/purchasing/po')
    await page.waitForLoadState('networkidle')

    // Find the Created By cell using automation ID
    const createdByCell = autoId(page, `PurchaseOrderView-created-by-${poId}`)
    await expect(createdByCell).toBeVisible({ timeout: 10000 })

    const createdByText = await createdByCell.innerText()

    // Should have a name, not be empty or just a dash
    expect(createdByText.trim()).not.toBe('')
    expect(createdByText.trim()).not.toBe('—')
    console.log(`List view - Created By: ${createdByText}`)

    // Navigate to PO detail
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    // Find the Created By field using automation ID
    const createdByInput = autoId(page, 'PoSummaryCard-created-by')
    await expect(createdByInput).toBeVisible({ timeout: 5000 })

    const createdByInputValue = await createdByInput.inputValue()

    expect(createdByInputValue.trim()).not.toBe('')
    console.log(`Detail view - Created By: ${createdByInputValue}`)

    // Both should match
    expect(createdByInputValue.trim()).toBe(createdByText.trim())
  })
})
