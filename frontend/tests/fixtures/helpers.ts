import type { Page, Response } from '@playwright/test'
import { expect } from '@playwright/test'
import { appendFileSync, existsSync, mkdirSync } from 'fs'
import path from 'path'

// Test data constants
export const TEST_CLIENT_NAME = 'ABC Carpet Cleaning TEST IGNORE'

// Network logging state
let networkRunId: string | null = null
let networkRunDate: string | null = null
const networkCsvPath = path.join(process.cwd(), 'test-results', 'network-aggregate.csv')

// Default max wire transfer size - catches bugs like missing filters
// 100KB is generous: a 192KB JSON response compresses to ~60-80KB via gzip
const DEFAULT_MAX_RESPONSE_KB = 100

/**
 * Helper to log all API network traffic with sizes and assert on response size.
 * Measures **wire transfer size** (compressed) via Playwright's request.sizes(),
 * not decompressed content size, so the limit reflects actual network cost.
 * Appends to test-results/network-aggregate.csv for later analysis.
 * Fails test if any API response exceeds maxResponseKB on the wire (default 100KB).
 * Call once at start of test to enable logging for that page.
 */
export function enableNetworkLogging(
  page: Page,
  testName?: string,
  options?: { maxResponseKB?: number },
) {
  const maxResponseKB = options?.maxResponseKB ?? DEFAULT_MAX_RESPONSE_KB

  // Initialize run ID once per test run
  if (!networkRunId) {
    networkRunId = Math.random().toString(36).substring(2, 10)
    networkRunDate = new Date().toISOString()
    // Ensure test-results directory exists
    const dir = path.dirname(networkCsvPath)
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
    // Write header if file doesn't exist
    if (!existsSync(networkCsvPath)) {
      appendFileSync(
        networkCsvPath,
        'run_id,run_date,test_name,method,url,status,wire_size_bytes,wire_size_kb,content_size_bytes,content_size_kb\n',
      )
    }
  }

  let compressionLogged = false

  page.on('response', async (response: Response) => {
    const url = response.url()
    // Strip base URL for readability
    const shortUrl = url.replace(/^https?:\/\/[^/]+/, '')

    // Skip dev server source files
    if (shortUrl.startsWith('/src/') || shortUrl.startsWith('/@')) {
      return
    }

    // Only log API calls, skip static assets
    if (!url.includes('/api/') && !url.includes('/clients/') && !url.includes('/jobs/')) {
      return
    }

    try {
      const request = response.request()
      const method = request.method()
      const status = response.status()

      // Get wire size (compressed bytes on the wire)
      const sizes = await request.sizes()
      const wireSizeBytes = sizes.responseBodySize
      const wireSizeKB = wireSizeBytes / 1024

      // Get decompressed content size for logging
      const body = await response.body()
      const contentSizeBytes = body.length
      const contentSizeKB = contentSizeBytes / 1024

      // Log compression headers once per test for diagnostics
      if (!compressionLogged) {
        const acceptEncoding = request.headers()['accept-encoding'] ?? '(none)'
        const contentEncoding = response.headers()['content-encoding'] ?? '(none)'
        console.log(
          `[NETWORK] Compression: Accept-Encoding: ${acceptEncoding}, Content-Encoding: ${contentEncoding}`,
        )
        compressionLogged = true
      }

      // Append to CSV
      const row = [
        networkRunId,
        networkRunDate,
        `"${testName || 'unknown'}"`,
        method,
        `"${shortUrl.replace(/"/g, '""')}"`,
        status,
        wireSizeBytes,
        wireSizeKB.toFixed(2),
        contentSizeBytes,
        contentSizeKB.toFixed(2),
      ].join(',')
      appendFileSync(networkCsvPath, row + '\n')

      // Assert on wire size (compressed transfer) - catch bugs like missing filters
      if (wireSizeKB > maxResponseKB) {
        throw new Error(
          `API response too large on wire: ${method} ${shortUrl} transferred ${wireSizeKB.toFixed(1)}KB ` +
            `(decompressed: ${contentSizeKB.toFixed(1)}KB, max wire: ${maxResponseKB}KB). ` +
            `This may indicate a missing filter or pagination bug.`,
        )
      }
    } catch (e) {
      // Re-throw size assertion errors
      if (e instanceof Error && e.message.includes('API response too large')) {
        throw e
      }
      // Ignore other errors (response body not available, e.g., redirects)
    }
  })
}

/**
 * Helper to time and log async operations
 */
export async function timed<T>(label: string, fn: () => Promise<T>): Promise<T> {
  const start = Date.now()
  try {
    const result = await fn()
    console.log(`[TIMING] ${label}: ${Date.now() - start}ms`)
    return result
  } catch (error) {
    console.log(`[TIMING] ${label}: FAILED after ${Date.now() - start}ms`)
    throw error
  }
}

/**
 * Helper to find elements by data-automation-id attribute
 */
export const autoId = (page: Page, id: string) => page.locator(`[data-automation-id="${id}"]`)

/**
 * Helper to find AG Grid row by row-id attribute
 */
export const gridRow = (page: Page, rowId: string) => page.locator(`[row-id="${rowId}"]`)

/**
 * Helper to find AG Grid cell by row-id and col-id
 */
export const gridCell = (page: Page, rowId: string, colId: string) =>
  page.locator(`[row-id="${rowId}"] [col-id="${colId}"]`)

/**
 * Helper to dismiss any toast notifications that might block interactions
 */
export async function dismissToasts(page: Page) {
  const toasts = page.locator('[data-sonner-toast]')

  const toastCount = await toasts.count()
  if (toastCount === 0) return

  for (let i = 0; i < toastCount; i++) {
    const toast = toasts.nth(i)
    const closeBtn = toast.locator('button[aria-label="Close toast"]')
    if (await closeBtn.count()) {
      await closeBtn.click()
    } else {
      await toast.click()
    }

    await page.waitForTimeout(100)
  }

  await page.waitForTimeout(300)
}

/**
 * Helper to wait for JobSettingsTab to finish initializing
 */
export async function waitForSettingsInitialized(page: Page) {
  await page.waitForSelector('[data-initialized="true"]', { timeout: 15000 })
}

/**
 * Helper to wait for autosave to complete
 * Handles job header saves, cost line creates/updates/deletes
 */
export async function waitForAutosave(page: Page) {
  await page.waitForResponse(
    (response) => {
      const url = response.url()
      const method = response.request().method()
      const status = response.status()

      // Job header save (PATCH, status 200)
      if (
        url.includes('/job/rest/jobs/') &&
        !url.includes('/cost_sets/') &&
        method === 'PATCH' &&
        status === 200
      ) {
        return true
      }

      // Cost line create (POST, status 201)
      if (
        url.includes('/cost_sets/') &&
        url.includes('/cost_lines') &&
        method === 'POST' &&
        status === 201
      ) {
        return true
      }

      // Cost line update (PATCH, status 200)
      if (url.includes('/job/rest/cost_lines/') && method === 'PATCH' && status === 200) {
        return true
      }

      // Cost line delete (DELETE, status 204)
      if (url.includes('/job/rest/cost_lines/') && method === 'DELETE' && status === 204) {
        return true
      }

      return false
    },
    { timeout: 10000 },
  )
}

/**
 * Create a new purchase order for testing and return its URL
 */
export async function createTestPurchaseOrder(page: Page): Promise<string> {
  const randomSuffix = Math.floor(Math.random() * 100000)
  const supplierName = `E2E Test Supplier ${randomSuffix}`

  // Navigate to create PO page
  await page.goto('/purchasing/po/create')
  await page.waitForLoadState('networkidle')

  // Create a new supplier using Ctrl+Enter
  const supplierInput = autoId(page, 'ClientLookup-input')
  await supplierInput.click()
  await supplierInput.fill(supplierName)
  await page.waitForTimeout(500)
  await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
  await autoId(page, 'ClientLookup-create-new').waitFor({ timeout: 5000 })
  await supplierInput.press('Control+Enter')

  // Wait for supplier creation
  await page.waitForTimeout(3000)

  // Verify Xero badge is green
  const xeroIndicator = autoId(page, 'ClientLookup-xero-valid')
  await expect(xeroIndicator).toBeVisible({ timeout: 10000 })

  // Add reference
  await autoId(page, 'PoSummaryCard-reference').fill(`E2E Test Ref ${randomSuffix}`)

  // Save the PO - wait for the API response
  const savePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/purchasing/rest/purchase-orders') &&
      response.request().method() === 'POST' &&
      response.status() === 201,
    { timeout: 30000 },
  )

  await autoId(page, 'PoCreateView-save').click()
  await savePromise

  // Wait for redirect to PO form
  await page.waitForURL(/\/purchasing\/po\/[a-f0-9-]+$/, { timeout: 15000 })

  const poUrl = page.url()
  console.log(`Created PO at: ${poUrl}`)

  return poUrl
}

/**
 * Create a new job for testing and return its URL
 */
export async function createTestJob(page: Page, jobNameSuffix: string): Promise<string> {
  const timestamp = Date.now()
  const jobName = `Test Job ${jobNameSuffix} ${timestamp}`

  await autoId(page, 'AppNavbar-create-job').click()
  await page.waitForURL('**/jobs/create')
  await page.waitForLoadState('networkidle')

  // Search and select client
  const clientInput = autoId(page, 'ClientLookup-input')
  await clientInput.click()
  await clientInput.fill('ABC')
  await page.waitForTimeout(500) // Give search time to trigger
  await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })

  await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()
  await expect(clientInput).toHaveValue(TEST_CLIENT_NAME)

  // Enter job details
  await autoId(page, 'JobCreateView-name-input').fill(jobName)
  await autoId(page, 'JobCreateView-estimated-materials').fill('0')
  await autoId(page, 'JobCreateView-estimated-time').fill('0')

  // Select contact
  await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })
  await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })

  const selectButtons = autoId(page, 'ContactSelectionModal-select-button')
  const selectButtonCount = await selectButtons.count()

  if (selectButtonCount > 0) {
    await selectButtons.first().click()
  } else {
    const submitButton = autoId(page, 'ContactSelectionModal-submit')
    await expect(submitButton).toHaveText('Create Contact', { timeout: 10000 })
    await autoId(page, 'ContactSelectionModal-name-input').fill(`Test Contact ${timestamp}`)
    await autoId(page, 'ContactSelectionModal-email-input').fill(`test${timestamp}@example.com`)
    await submitButton.click()
  }

  await autoId(page, 'ContactSelectionModal-container').waitFor({ state: 'hidden', timeout: 10000 })
  await dismissToasts(page)

  // Set pricing method to T&M and submit
  await autoId(page, 'JobCreateView-pricing-method').selectOption('time_materials')
  await dismissToasts(page)
  await autoId(page, 'JobCreateView-submit').click({ force: true })
  await page.waitForURL('**/jobs/*?*tab=estimate*', { timeout: 15000 })

  return page.url()
}
