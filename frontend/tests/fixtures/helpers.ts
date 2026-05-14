import type { Page, Response } from '@playwright/test'
import { expect, test } from '@playwright/test'
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

/** Generous safety-net timeout — used where we just need to avoid hanging forever. */
const INFINITE_TIMEOUT = 120000

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
        'run_id,run_date,test_name,method,url,status,wire_size_bytes,wire_size_kb,content_size_bytes,content_size_kb,duration_ms\n',
      )
    }
  }

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

    // Generated-PDF endpoints stream multi-hundred-KB binaries by design;
    // the wire-size guard is meant to catch missing-filter bugs on JSON
    // listings, not flag legitimate document downloads.
    const isGeneratedPdfEndpoint =
      url.includes('/delivery-docket/') || url.includes('/workshop-pdf/')

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

      // Get response timing for layer-attribution analysis.
      // timing() returns null for cached/redirect/304 responses.
      let durationMs = ''
      try {
        const timing = response.timing()
        if (timing) {
          durationMs = String(Math.round(timing.responseEnd - timing.startTime))
        }
      } catch {
        // timing() is not available for all responses
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
        durationMs,
      ].join(',')
      appendFileSync(networkCsvPath, row + '\n')

      // Assert on wire size (compressed transfer) - catch bugs like missing filters
      if (wireSizeKB > maxResponseKB && !isGeneratedPdfEndpoint) {
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
 * Helper to find elements by data-automation-id attribute
 */
export const autoId = (page: Page, id: string) => page.locator(`[data-automation-id="${id}"]`)

/**
 * Run a semantic Playwright step whose duration is logged to
 * step-timing-aggregate.csv for offline budget analysis. maxMs is
 * documentation-only — the step never fails on timing; hard timeouts are
 * governed by the test-level 120s and the INFINITE_TIMEOUT safety net.
 */
export async function expectStepUnder<T>(
  title: string,
  maxMs: number,
  body: () => Promise<T>,
): Promise<T> {
  return await test.step(title, body)
}

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
 * SmartTimesheetTable always renders an empty phantom row at the end of the
 * table. Returns the index of that phantom (= number of saved entries on the
 * current day for this staff member). Don't hard-code rowIndex=0 — picked
 * staff/date may already have entries.
 */
export async function getPhantomRowIndex(page: Page): Promise<number> {
  const rows = page.locator('[data-automation-id^="DataTable-row-"]')
  // Initial mount can take a moment after the URL changes; the staff store
  // and timesheet entries load asynchronously before SmartTimesheetTable
  // becomes visible. Wait for at least one row before counting.
  await rows.first().waitFor({ timeout: 15000 })
  return (await rows.count()) - 1
}

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
        url.includes('/api/job/jobs/') &&
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
      if (url.includes('/api/job/cost_lines/') && method === 'PATCH' && status === 200) {
        return true
      }

      // Cost line delete (DELETE, status 204)
      if (url.includes('/api/job/cost_lines/') && method === 'DELETE' && status === 204) {
        return true
      }

      return false
    },
    { timeout: INFINITE_TIMEOUT },
  )
}

/**
 * Create a new purchase order for testing and return its URL
 */
export async function createTestPurchaseOrder(page: Page): Promise<string> {
  const randomSuffix = Math.floor(Math.random() * 100000)
  const supplierName = `[TEST] Supplier ${randomSuffix}`

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
  await autoId(page, 'PoSummaryCard-reference').fill(`[TEST] PO Ref ${randomSuffix}`)

  // Save the PO - wait for the API response
  const savePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/api/purchasing/purchase-orders') &&
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
  const jobName = `[TEST] Job ${jobNameSuffix} ${timestamp}`

  await expectStepUnder('createTestJob: navigate to create job page', 2500, async () => {
    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')
    await page.waitForLoadState('networkidle')
  })

  await expectStepUnder('createTestJob: search and select client', 1500, async () => {
    const clientInput = autoId(page, 'ClientLookup-input')
    await clientInput.click()
    await clientInput.fill('ABC')
    await page.waitForTimeout(500) // Give search time to trigger
    await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })

    await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()
    await expect(clientInput).toHaveValue(TEST_CLIENT_NAME)
  })

  await expectStepUnder('createTestJob: fill job details', 1000, async () => {
    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('0')
    await autoId(page, 'JobCreateView-estimated-time').fill('0')
  })

  // Select contact
  await expectStepUnder('createTestJob: open contact modal', 1000, async () => {
    await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })
  })

  const selectButtonCount = await expectStepUnder(
    'createTestJob: inspect contact modal branch',
    250,
    async () => {
      const selectButtons = autoId(page, 'ContactSelectionModal-select-button')
      return await selectButtons.count()
    },
  )

  if (selectButtonCount > 0) {
    await expectStepUnder('createTestJob: select existing contact', 1000, async () => {
      await autoId(page, 'ContactSelectionModal-select-button').first().click()
    })
  } else {
    await expectStepUnder('createTestJob: create new contact', 2000, async () => {
      const submitButton = autoId(page, 'ContactSelectionModal-submit')
      await expect(submitButton).toHaveText('Create Contact', { timeout: 10000 })
      await autoId(page, 'ContactSelectionModal-name-input').fill(`[TEST] Contact ${timestamp}`)
      await autoId(page, 'ContactSelectionModal-email-input').fill(`test${timestamp}@example.com`)
      await submitButton.click()
    })
  }

  await expectStepUnder('createTestJob: wait for contact modal to close', 1500, async () => {
    await autoId(page, 'ContactSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })
  })
  await expectStepUnder('createTestJob: submit job', 3500, async () => {
    await dismissToasts(page)
    await autoId(page, 'JobCreateView-pricing-method').selectOption('time_materials')
    await dismissToasts(page)
    await autoId(page, 'JobCreateView-submit').click({ force: true })
    await page.waitForURL('**/jobs/*?*tab=estimate*', { timeout: 15000 })
  })

  return page.url()
}
