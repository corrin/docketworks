import type { Page, Response } from '@playwright/test'
import { expect, test } from '@playwright/test'
import { appendFileSync, existsSync, mkdirSync } from 'fs'
import path from 'path'

// Test data constants
export const TEST_COMPANY_NAME = 'ABC Carpet Cleaning TEST IGNORE'

// Network logging state
let networkRunId: string | null = null
let networkRunDate: string | null = null
const networkCsvPath = path.join(process.cwd(), 'test-results', 'network-aggregate.csv')

// Default max wire transfer size - catches bugs like missing filters
// 100KB is generous: a 192KB JSON response compresses to ~60-80KB via gzip
const DEFAULT_MAX_RESPONSE_KB = 100

/** Generous safety-net timeout — used where we just need to avoid hanging forever. */
export const INFINITE_TIMEOUT = 120000

type JsonObject = Record<string, unknown>

type CreatedCompanySummary = {
  name: string
  xeroContactId: string
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function parseCompanyCreateResponse(response: Response): Promise<CreatedCompanySummary> {
  const responseText = await response.text()
  let body: unknown

  try {
    body = JSON.parse(responseText)
  } catch {
    throw new Error(`Company create returned non-JSON response: ${responseText}`)
  }

  if (!response.ok()) {
    throw new Error(`Company create failed with HTTP ${response.status()}: ${responseText}`)
  }

  if (!isJsonObject(body) || body.success !== true || !isJsonObject(body.company)) {
    throw new Error(`Company create returned unsuccessful payload: ${responseText}`)
  }

  const name = body.company.name
  const xeroContactId = body.company.xero_contact_id
  if (typeof name !== 'string' || name.length === 0) {
    throw new Error(`Company create returned missing company name: ${responseText}`)
  }
  if (typeof xeroContactId !== 'string' || xeroContactId.length === 0) {
    throw new Error(`Company create returned company without Xero ID: ${responseText}`)
  }

  return { name, xeroContactId }
}

export async function waitForCompanyCreateResponse(
  page: Page,
  action: () => Promise<void>,
): Promise<CreatedCompanySummary> {
  const responsePromise = page.waitForResponse(
    (candidate) => {
      const url = new URL(candidate.url())
      return url.pathname === '/api/companies/create/' && candidate.request().method() === 'POST'
    },
    { timeout: 30000 },
  )

  await action()
  const response = await responsePromise
  return await parseCompanyCreateResponse(response)
}

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
    if (!url.includes('/api/') && !url.includes('/companies/') && !url.includes('/jobs/')) {
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

async function waitForJobCreateResponse(page: Page): Promise<string> {
  const response = await page.waitForResponse(
    (candidate) => {
      const url = new URL(candidate.url())
      return (
        url.pathname === '/api/job/jobs/' &&
        candidate.request().method() === 'POST' &&
        candidate.status() === 201
      )
    },
    { timeout: INFINITE_TIMEOUT },
  )

  const body: unknown = await response.json()
  if (!body || typeof body !== 'object' || !('job_id' in body) || typeof body.job_id !== 'string') {
    throw new Error(`Job create response did not include job_id: ${JSON.stringify(body)}`)
  }

  return body.job_id
}

export async function waitForCurrentUrl(page: Page, expectedUrl: RegExp): Promise<void> {
  await page.waitForFunction(
    ({ source, flags }) => new RegExp(source, flags).test(window.location.href),
    { source: expectedUrl.source, flags: expectedUrl.flags },
    { timeout: INFINITE_TIMEOUT },
  )
}

export async function submitJobAndWaitForCreatedJob(
  page: Page,
  expectedTab: 'estimate' | 'quote',
): Promise<string> {
  const createResponsePromise = waitForJobCreateResponse(page)
  const submitButton = autoId(page, 'JobCreateView-submit')
  await expect(submitButton).toBeEnabled()
  await submitButton.click()

  const jobId = await createResponsePromise
  await waitForCurrentUrl(page, new RegExp(`/jobs/${jobId}(?:\\?.*)?$`))

  const url = new URL(page.url())
  if (url.searchParams.get('tab') !== expectedTab) {
    throw new Error(
      `Expected created job ${jobId} to open tab=${expectedTab}, got ${url.searchParams.get('tab')}`,
    )
  }

  return page.url()
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
  const supplierInput = autoId(page, 'CompanyLookup-input')
  await supplierInput.click()
  await supplierInput.fill(supplierName)
  await page.waitForTimeout(500)
  await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
  await autoId(page, 'CompanyLookup-create-new').waitFor({ timeout: 5000 })
  await waitForCompanyCreateResponse(page, async () => {
    await supplierInput.press('Control+Enter')
  })

  // Verify Xero badge is green
  const xeroIndicator = autoId(page, 'CompanyLookup-xero-valid')
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

  await expectStepUnder('createTestJob: search and select company', 1500, async () => {
    const companyInput = autoId(page, 'CompanyLookup-input')
    await companyInput.click()
    await companyInput.fill('ABC')
    await page.waitForTimeout(500) // Give search time to trigger
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })

    await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()
    await expect(companyInput).toHaveValue(TEST_COMPANY_NAME)
  })

  await expectStepUnder('createTestJob: fill job details', 1000, async () => {
    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('0')
    await autoId(page, 'JobCreateView-estimated-time').fill('0')
  })

  // Select person
  await expectStepUnder('createTestJob: open person modal', 1000, async () => {
    await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })
  })

  const selectButtonCount = await expectStepUnder(
    'createTestJob: inspect person modal branch',
    250,
    async () => {
      const selectButtons = autoId(page, 'PersonSelectionModal-select-button')
      return await selectButtons.count()
    },
  )

  if (selectButtonCount > 0) {
    await expectStepUnder('createTestJob: select existing person', 1000, async () => {
      await autoId(page, 'PersonSelectionModal-select-button').first().click()
    })
  } else {
    await expectStepUnder('createTestJob: create new person', 2000, async () => {
      const submitButton = autoId(page, 'PersonSelectionModal-submit')
      await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })
      await autoId(page, 'PersonSelectionModal-name-input').fill(`[TEST] Person ${timestamp}`)
      await autoId(page, 'PersonSelectionModal-email-input').fill(`test${timestamp}@example.com`)
      await submitButton.click()
    })
  }

  await expectStepUnder('createTestJob: wait for person modal to close', 1500, async () => {
    await autoId(page, 'PersonSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })
  })
  await expectStepUnder('createTestJob: submit job', 3500, async () => {
    await dismissToasts(page)
    await autoId(page, 'JobCreateView-pricing-method').selectOption('time_materials')
    await dismissToasts(page)
    await submitJobAndWaitForCreatedJob(page, 'estimate')
  })

  return page.url()
}
