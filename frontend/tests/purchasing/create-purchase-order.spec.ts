import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { autoId, createTestJob, createTestPurchaseOrder } from '../fixtures/helpers'

/**
 * Tests for purchase order operations.
 * Creates a PO, adds line items, assigns job, verifies data.
 */

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Wait for PO autosave to complete
 */
async function waitForPoAutosave(page: Page): Promise<void> {
  await page.waitForResponse(
    (response) => {
      const url = response.url()
      const method = response.request().method()
      const status = response.status()

      // PO header/lines save (PATCH, status 200)
      if (
        url.includes('/purchasing/rest/purchase-orders/') &&
        method === 'PATCH' &&
        status === 200
      ) {
        return true
      }

      return false
    },
    { timeout: 10000 },
  )
}

// ============================================================================
// Test Suite: Purchase Order Operations
// ============================================================================

test.describe.serial('purchase order operations', () => {
  let poUrl: string
  let jobNumber: string

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

    // Create a job for PO line assignment testing
    const jobUrl = await createTestJob(page, 'PurchaseOrder')
    console.log(`Created job at: ${jobUrl}`)

    // Extract job number from the page
    await page.goto(jobUrl.split('?')[0])
    await page.waitForLoadState('networkidle')
    const jobNumberElement = autoId(page, 'JobView-job-number').first()
    await jobNumberElement.waitFor({ timeout: 10000 })
    const jobNumberText = await jobNumberElement.innerText()
    const match = jobNumberText.match(/#(\d+)/)
    jobNumber = match ? match[1] : ''
    console.log(`Extracted job number: ${jobNumber}`)
    if (!jobNumber) {
      throw new Error(`Failed to extract job number from: "${jobNumberText}"`)
    }

    // Create a purchase order using helper
    poUrl = await createTestPurchaseOrder(page)
    console.log(`Created PO at: ${poUrl}`)

    await context.close()
  })

  test('add a line item to the purchase order', async ({ authenticatedPage: page }) => {
    // Navigate to the created PO
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Click Add line button to create a new line
    await autoId(page, 'PoLinesTable-add-line').click()
    await page.waitForTimeout(1000)

    // Wait for the description input to appear (indicates line was added)
    const descriptionInput = autoId(page, 'PoLinesTable-description-0')
    await descriptionInput.waitFor({ timeout: 10000 })

    // Fill in line details
    await descriptionInput.fill('Test Material Item')
    await page.waitForTimeout(300)

    // Fill quantity
    const qtyInput = autoId(page, 'PoLinesTable-quantity-0')
    await qtyInput.clear()
    await qtyInput.fill('5')
    await page.waitForTimeout(300)

    // Fill unit cost
    const costInput = autoId(page, 'PoLinesTable-unit-cost-0')
    await costInput.clear()
    await costInput.fill('25.50')
    await page.waitForTimeout(300)

    // Wait for autosave
    await waitForPoAutosave(page)
    await page.waitForTimeout(500)

    console.log('Added line item: Test Material Item, qty 5 @ $25.50')
  })

  test('assign job to purchase order line using JobSelect', async ({ authenticatedPage: page }) => {
    // Navigate to the created PO
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Find the job select input (should be in the line we added)
    const jobSearchInput = autoId(page, 'JobSelect-job-search')
    await jobSearchInput.waitFor({ timeout: 10000 })

    // Click to focus and open dropdown
    await jobSearchInput.click()
    await page.waitForTimeout(300)

    // Type the job number to search
    await jobSearchInput.fill(jobNumber)
    await page.waitForTimeout(500)

    // Wait for dropdown to appear and show options
    const dropdown = autoId(page, 'JobSelect-dropdown')
    await dropdown.waitFor({ timeout: 5000 })

    // Select the job from the dropdown
    const jobOption = autoId(page, `JobSelect-option-${jobNumber}`)
    await jobOption.waitFor({ timeout: 5000 })
    await jobOption.click()
    await page.waitForTimeout(500)

    // Wait for autosave
    await waitForPoAutosave(page)

    // Verify job was selected - input should show job number
    const inputValue = await jobSearchInput.inputValue()
    expect(inputValue).toContain(jobNumber)

    console.log(`Assigned job ${jobNumber} to PO line`)
  })

  test('verify purchase order status can be changed', async ({ authenticatedPage: page }) => {
    // Navigate to the created PO
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    // Open status dropdown
    await autoId(page, 'PoSummaryCard-status-trigger').click()
    await page.waitForTimeout(300)

    // Select "Submitted to Supplier"
    await autoId(page, 'PoSummaryCard-status-submitted').click()
    await page.waitForTimeout(500)

    // Wait for autosave
    await waitForPoAutosave(page)

    // Verify status changed
    const statusTrigger = autoId(page, 'PoSummaryCard-status-trigger')
    await expect(statusTrigger).toContainText('Submitted')

    console.log('Changed PO status to Submitted')
  })
})
