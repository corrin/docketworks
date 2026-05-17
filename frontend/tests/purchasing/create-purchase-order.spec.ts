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
        url.includes('/api/purchasing/purchase-orders/') &&
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

    await expect(autoId(page, 'PoLinesTable-add-line')).toHaveCount(0)

    // The first editable row is autocreated, matching the timesheet entry flow.
    const descriptionInput = autoId(page, 'PoLinesTable-description-0')
    await descriptionInput.waitFor({ timeout: 10000 })

    const openStartedAt = Date.now()
    await page.getByRole('button', { name: 'Select Item' }).first().click()

    const searchInput = page.getByPlaceholder('Search items by description, code, or type...')
    await searchInput.waitFor({ timeout: 10000 })
    await expect(searchInput).toBeFocused({ timeout: 5000 })
    const openMs = Date.now() - openStartedAt

    const searchStartedAt = Date.now()
    const searchResponsePromise = page.waitForResponse(
      (response) => {
        if (!response.url().includes('/api/purchasing/stock/search/')) return false
        if (response.request().method() !== 'GET') return false
        if (response.status() !== 200) return false
        return new URL(response.url()).searchParams.get('q') === '5mm Round Bar'
      },
      { timeout: 10000 },
    )

    await searchInput.fill('5mm Round Bar')

    const searchResponse = await searchResponsePromise
    const searchBody = await searchResponse.json()
    const searchMs = Date.now() - searchStartedAt
    expect(Array.isArray(searchBody.results)).toBe(true)
    expect(searchBody.results.length).toBeGreaterThan(0)

    const selected = searchBody.results[0]
    const optionAutomationId = selected.item_code || selected.id
    const selectStartedAt = Date.now()
    await autoId(page, `ItemSelect-option-${optionAutomationId}`).click({ timeout: 10000 })
    const selectMs = Date.now() - selectStartedAt

    await expect(descriptionInput).toHaveValue(selected.description, { timeout: 10000 })

    const qtyInput = autoId(page, 'PoLinesTable-quantity-0')
    await qtyInput.fill('5')

    const autosavePromise = waitForPoAutosave(page)
    const costInput = autoId(page, 'PoLinesTable-unit-cost-0')
    await costInput.click()
    await page.keyboard.press('Tab')

    await autosavePromise
    await page.waitForTimeout(500)

    console.log(
      `PO ItemSelect timing: open=${openMs}ms search=${searchMs}ms select=${selectMs}ms item="${selected.description}"`,
    )
  })

  test('assign job to purchase order line using JobSelect', async ({ authenticatedPage: page }) => {
    // Navigate to the created PO
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Target the saved PO line; the phantom row also has a JobSelect.
    const jobSearchInput = autoId(page, 'DataTable-row-0').locator(
      '[data-automation-id="JobSelect-job-search"]',
    )
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
