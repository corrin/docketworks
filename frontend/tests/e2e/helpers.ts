import type { Page, Response } from '@playwright/test'
import { expect, test } from '@playwright/test'
import { appendFileSync, existsSync, mkdirSync } from 'fs'
import path from 'path'

/** The live-Xero-linked seed company every UI-seeded spec searches for. */
export const TEST_COMPANY_NAME = 'ABC Carpet Cleaning TEST IGNORE'

let networkRunId: string | null = null
let networkRunDate: string | null = null
const networkCsvPath = path.join(process.cwd(), 'test-results', 'network-aggregate.csv')

// 100KB is generous: a 192KB JSON response compresses to ~60-80KB via gzip
const DEFAULT_MAX_RESPONSE_KB = 100

/** Generous safety-net timeout — used where we just need to avoid hanging forever. */
export const INFINITE_TIMEOUT = 120000

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
): () => Promise<void> {
  const maxResponseKB = options?.maxResponseKB ?? DEFAULT_MAX_RESPONSE_KB

  if (!networkRunId) {
    networkRunId = Math.random().toString(36).substring(2, 10)
    networkRunDate = new Date().toISOString()
    const dir = path.dirname(networkCsvPath)
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
    if (!existsSync(networkCsvPath)) {
      appendFileSync(
        networkCsvPath,
        'run_id,run_date,test_name,method,url,status,wire_size_bytes,wire_size_kb,content_size_bytes,content_size_kb,duration_ms\n',
      )
    }
  }

  const pending = new Set<Promise<void>>()
  const failures: Error[] = []

  const inspectResponse = async (response: Response): Promise<void> => {
    const url = response.url()
    const shortUrl = url.replace(/^https?:\/\/[^/]+/, '')

    // Every backend route lives under /api/ (single NinjaAPI); anything else
    // is the SPA shell or a static asset. v1 also matched /companies/ and
    // /jobs/, but in v2 those are page navigations, not API calls.
    if (!shortUrl.startsWith('/api/')) {
      return
    }

    // Generated-PDF endpoints stream multi-hundred-KB binaries by design;
    // the wire-size guard is meant to catch missing-filter bugs on JSON
    // listings, not flag legitimate document downloads.
    const isGeneratedPdfEndpoint =
      url.includes('/delivery-docket/') || url.includes('/workshop-pdf/')

    const request = response.request()
    const method = request.method()
    const status = response.status()

    // Wire size is the compressed transfer; content size the decompressed
    // body. The guard asserts on the wire, which is what the user pays for.
    let wireSizeBytes: number
    let contentSizeBytes: number
    try {
      wireSizeBytes = (await request.sizes()).responseBodySize
      contentSizeBytes = (await response.body()).length
    } catch {
      // Redirects and aborted requests have no retrievable body; nothing to
      // measure or assert for them.
      return
    }
    const wireSizeKB = wireSizeBytes / 1024
    const contentSizeKB = contentSizeBytes / 1024

    // timing() never returns null; unavailable values are -1 (e.g. HAR
    // replay), which must not produce a negative duration in the CSV.
    const timing = request.timing()
    const durationMs =
      timing.responseEnd >= 0 && timing.startTime >= 0
        ? String(Math.round(timing.responseEnd - timing.startTime))
        : ''

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

    if (wireSizeKB > maxResponseKB && !isGeneratedPdfEndpoint) {
      throw new Error(
        `API response too large on wire: ${method} ${shortUrl} transferred ${wireSizeKB.toFixed(1)}KB ` +
          `(decompressed: ${contentSizeKB.toFixed(1)}KB, max wire: ${maxResponseKB}KB). ` +
          `This may indicate a missing filter or pagination bug.`,
      )
    }
  }

  const pendingUrls = new Map<Promise<void>, string>()

  const onResponse = (response: Response): void => {
    const inspection = inspectResponse(response)
      .catch((error: unknown) => {
        failures.push(error instanceof Error ? error : new Error(String(error)))
      })
      .finally(() => {
        pending.delete(inspection)
        pendingUrls.delete(inspection)
      })
    pending.add(inspection)
    pendingUrls.set(inspection, response.url())
  }
  page.on('response', onResponse)

  return async () => {
    page.off('response', onResponse)
    // A request may legitimately outlive its test (a late debounce fire, a
    // background refetch), and sizes()/body() on one never settles — an
    // unbounded drain would hang teardown for the full 120s with no clue.
    // Wait briefly, then name what was abandoned; only SETTLED inspections
    // can carry size violations, so nothing measurable is lost.
    const drained = await Promise.race([
      Promise.all(pending).then(() => true),
      new Promise<false>((resolve) => setTimeout(() => resolve(false), 10_000)),
    ])
    if (!drained) {
      const abandoned = [...pendingUrls.values()].join(', ')
      process.stdout.write(
        `[network] ${pendingUrls.size} response inspection(s) still pending at teardown ` +
          `(request outlived the test): ${abandoned}\n`,
      )
    }
    if (failures.length > 0) {
      throw new AggregateError(failures, `Network logging found ${failures.length} failure(s)`)
    }
  }
}

/** Find an element by the stable data-automation-id contract. */
export const autoId = (page: Page, id: string) => page.locator(`[data-automation-id="${id}"]`)

/** Wait for JobSettingsTab to finish initializing. */
export async function waitForSettingsInitialized(page: Page) {
  await page.waitForSelector('[data-initialized="true"]', { timeout: 15000 })
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
 * Wait for an autosave to land: a job-header PATCH or any cost-line write.
 * PATCH, not PUT — jobJobsUpdate shares the URL but is not the autosave path.
 */
export async function waitForAutosave(page: Page) {
  await page.waitForResponse(
    (response) => {
      const url = response.url()
      const method = response.request().method()
      const status = response.status()

      if (
        url.includes('/api/job/jobs/') &&
        !url.includes('/cost_sets/') &&
        method === 'PATCH' &&
        status === 200
      ) {
        return true
      }
      if (
        url.includes('/cost_sets/') &&
        url.includes('/cost_lines') &&
        method === 'POST' &&
        status === 201
      ) {
        return true
      }
      if (url.includes('/api/job/cost_lines/') && method === 'PATCH' && status === 200) {
        return true
      }
      if (url.includes('/api/job/cost_lines/') && method === 'DELETE' && status === 204) {
        return true
      }
      return false
    },
    { timeout: INFINITE_TIMEOUT },
  )
}

interface CreateTestJobOptions {
  /** Overrides the default `[TEST] Job <suffix> <ts>` name entirely. */
  jobName?: string
  materials?: string
  time?: string
  pricing?: 'fixed_price' | 'time_materials'
}

/** Create a fresh [TEST] job through the UI and return its detail URL. */
export async function createTestJob(
  page: Page,
  jobNameSuffix: string,
  options?: CreateTestJobOptions,
): Promise<string> {
  const timestamp = Date.now()
  const jobName = options?.jobName ?? `[TEST] Job ${jobNameSuffix} ${timestamp}`
  const materials = options?.materials ?? '0'
  const time = options?.time ?? '0'
  const pricing = options?.pricing ?? 'time_materials'

  await test.step('createTestJob: navigate to create job page', async () => {
    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')
    await page.waitForLoadState('networkidle')
  })

  await test.step('createTestJob: search and select company', async () => {
    const companyInput = autoId(page, 'CompanyLookup-input')
    await companyInput.click()
    await companyInput.fill('ABC')
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()
    await expect(companyInput).toHaveValue(TEST_COMPANY_NAME)
  })

  await test.step('createTestJob: fill job details', async () => {
    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill(materials)
    await autoId(page, 'JobCreateView-estimated-time').fill(time)
  })

  await test.step('createTestJob: select or create person', async () => {
    await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

    // The select-or-create branch must not race the people load: a count
    // taken mid-load reads 0 and creates a duplicate person.
    await page.getByText('Loading people...').waitFor({ state: 'hidden', timeout: 10000 })

    const selectButtons = autoId(page, 'PersonSelectionModal-select-button')
    if ((await selectButtons.count()) > 0) {
      // The Select button sits in a hover-revealed overlay on the card.
      const firstCard = page.locator('[data-automation-id^="PersonSelectionModal-card-"]').first()
      await firstCard.hover()
      await firstCard.locator('[data-automation-id="PersonSelectionModal-select-button"]').click()
    } else {
      const submitButton = autoId(page, 'PersonSelectionModal-submit')
      await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })
      await autoId(page, 'PersonSelectionModal-name-input').fill(`[TEST] Person ${timestamp}`)
      await autoId(page, 'PersonSelectionModal-email-input').fill(`test${timestamp}@example.com`)
      await submitButton.click()
    }

    await autoId(page, 'PersonSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })
  })

  await test.step('createTestJob: submit job', async () => {
    await dismissToasts(page)
    await autoId(page, 'JobCreateView-pricing-method').selectOption(pricing)
    await dismissToasts(page)
    await submitJobAndWaitForCreatedJob(page, pricing === 'fixed_price' ? 'quote' : 'estimate')
  })

  return page.url()
}

/** Extract the job UUID from a job-detail URL. */
export function getJobIdFromUrl(url: string): string {
  const jobId = url.match(/\/jobs\/([0-9a-f-]{36})/i)?.[1]
  if (!jobId) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return jobId
}

export async function waitForCurrentUrl(page: Page, expectedUrl: RegExp): Promise<void> {
  await page.waitForFunction(
    ({ source, flags }) => new RegExp(source, flags).test(window.location.href),
    { source: expectedUrl.source, flags: expectedUrl.flags },
    { timeout: INFINITE_TIMEOUT },
  )
}

/** Dismiss any sonner toasts that might block interactions. */
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
