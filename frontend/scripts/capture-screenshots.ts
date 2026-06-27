import { chromium, type Page, type Response } from '@playwright/test'
import * as fs from 'fs/promises'
import * as path from 'path'
import { fileURLToPath, pathToFileURL } from 'url'
import { parseArgs, type CliOptions } from '@/utils/captureScreenshots'
import 'dotenv/config'
import { getBackendEnv } from '../tests/scripts/db-backup-utils'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// Screenshot definition type
interface ScreenshotDef {
  id: string // Stable identifier used in markdown references
  description: string // Human-readable description for manifest
  route: string // URL path to navigate to
  waitFor?: string // CSS selector to wait for before capturing
  prepare?: (page: Page) => Promise<void> // Optional setup actions
  fullPage?: boolean // Capture entire scrollable page
  clip?: { x: number; y: number; width: number; height: number } // Capture specific region
}

interface PageDiagnostics {
  screenshot: string
  diagnostics: string
  initialStatus: number | null
  finalUrl: string
  title: string
  loginDetected: boolean
  routeMismatch: boolean
  headings: string[]
  failedResponses: Array<{
    method: string
    status: number
    url: string
  }>
  bodyPreview: string
}

// Define all screenshots to capture
// Naming convention: {domain}-{action}-{state}.png
const SCREENSHOTS: ScreenshotDef[] = [
  // === LOGIN ===
  {
    id: 'login-page',
    description: 'Login page with email and password fields',
    route: '/login',
    waitFor: '#username',
  },

  // === KANBAN / JOBS ===
  {
    id: 'kanban-board-overview',
    description: 'Kanban board showing job cards organized by status',
    route: '/kanban',
    waitFor: '[data-automation-id="kanban-column"]',
  },

  // === JOB CREATION ===
  {
    id: 'job-create-form',
    description: 'Create new job form with client, name, and description fields',
    route: '/jobs/create',
    waitFor: 'form',
  },

  // === JOB DETAILS ===
  {
    id: 'job-details-form',
    description: 'Job details form showing job number, name, client, and description',
    route: '/kanban',
    waitFor: '[data-automation-id="kanban-column"]',
    prepare: async (page: Page) => {
      // Click the first job card to open a job
      const firstJob = page.locator('[data-automation-id="job-card"]').first()
      if (await firstJob.isVisible()) {
        await firstJob.click()
        await page.waitForSelector('[data-automation-id="job-view"]', { timeout: 10000 })
      }
    },
  },

  // === JOB ESTIMATE TAB ===
  {
    id: 'job-estimate-tab',
    description: 'Job Estimate tab showing time, materials, and adjustments grids',
    route: '/kanban',
    waitFor: '[data-automation-id="kanban-column"]',
    prepare: async (page: Page) => {
      const firstJob = page.locator('[data-automation-id="job-card"]').first()
      if (await firstJob.isVisible()) {
        await firstJob.click()
        await page.waitForSelector('[data-automation-id="job-view"]', { timeout: 10000 })
        // Click the Estimate tab
        const estimateTab = page.getByRole('tab', { name: /estimate/i })
        if (await estimateTab.isVisible()) await estimateTab.click()
        await page.waitForTimeout(1000)
      }
    },
    fullPage: true,
  },

  // === JOB QUOTE TAB ===
  {
    id: 'job-quote-tab',
    description: 'Job Quote tab showing customer-facing pricing',
    route: '/kanban',
    waitFor: '[data-automation-id="kanban-column"]',
    prepare: async (page: Page) => {
      const firstJob = page.locator('[data-automation-id="job-card"]').first()
      if (await firstJob.isVisible()) {
        await firstJob.click()
        await page.waitForSelector('[data-automation-id="job-view"]', { timeout: 10000 })
        const quoteTab = page.getByRole('tab', { name: /quote/i })
        if (await quoteTab.isVisible()) await quoteTab.click()
        await page.waitForTimeout(1000)
      }
    },
    fullPage: true,
  },

  // === JOB ACTUAL/REALITY TAB ===
  {
    id: 'job-actual-tab',
    description: 'Job Reality/Actual tab showing real costs and revenue',
    route: '/kanban',
    waitFor: '[data-automation-id="kanban-column"]',
    prepare: async (page: Page) => {
      const firstJob = page.locator('[data-automation-id="job-card"]').first()
      if (await firstJob.isVisible()) {
        await firstJob.click()
        await page.waitForSelector('[data-automation-id="job-view"]', { timeout: 10000 })
        const actualTab = page.getByRole('tab', { name: /actual/i })
        if (await actualTab.isVisible()) await actualTab.click()
        await page.waitForTimeout(1000)
      }
    },
    fullPage: true,
  },

  // === JOB ATTACHMENTS TAB ===
  {
    id: 'job-attachments-tab',
    description: 'Job Attachments tab showing file upload area and attached files',
    route: '/kanban',
    waitFor: '[data-automation-id="kanban-column"]',
    prepare: async (page: Page) => {
      const firstJob = page.locator('[data-automation-id="job-card"]').first()
      if (await firstJob.isVisible()) {
        await firstJob.click()
        await page.waitForSelector('[data-automation-id="job-view"]', { timeout: 10000 })
        const attachTab = page.getByRole('tab', { name: /attachment/i })
        if (await attachTab.isVisible()) await attachTab.click()
        await page.waitForTimeout(1000)
      }
    },
  },

  // === TIMESHEETS ===
  {
    id: 'timesheet-entry-grid',
    description: 'Timesheet entry grid with staff selector, date picker, and hours',
    route: '/timesheets/entry',
    waitFor: 'main',
  },
  {
    id: 'timesheet-daily-overview',
    description: 'Daily timesheet overview with bar chart and staff hours',
    route: '/timesheets/daily',
    waitFor: 'main',
  },

  // === PURCHASING ===
  {
    id: 'purchasing-po-list',
    description: 'Purchase Orders list page',
    route: '/purchasing/po',
    waitFor: 'main',
  },
  {
    id: 'purchasing-po-create',
    description: 'Create Purchase Order form with supplier and reference fields',
    route: '/purchasing/po/create',
    waitFor: 'form',
  },

  // === REPORTS ===
  {
    id: 'kpi-report-overview',
    description: 'KPI Report with summary cards and calendar heatmap',
    route: '/reports/kpi',
    waitFor: 'main',
    fullPage: true,
  },
  {
    id: 'payroll-reconciliation',
    description: 'Payroll Reconciliation report with summary cards and heatmap grid',
    route: '/reports/payroll-reconciliation',
    waitFor: 'main',
    fullPage: true,
  },

  // === CLIENTS ===
  {
    id: 'clients-list',
    description: 'Client list with search and filters',
    route: '/crm/clients',
    waitFor: 'main',
  },

  // === ADMIN ===
  {
    id: 'admin-company-settings',
    description: 'Company settings configuration page',
    route: '/admin/company',
    waitFor: 'form',
  },
  {
    id: 'admin-staff-list',
    description: 'Staff Management page with staff table',
    route: '/admin/staff',
    waitFor: 'main',
  },
]

// Output paths
const OUTPUT_DIR = path.resolve(__dirname, '../manual/public/screenshots')
const MANIFEST_PATH = path.resolve(__dirname, '../manual/screenshot-manifest.json')

function getBaseUrl(): string {
  const backendEnv = getBackendEnv()
  const appDomain = backendEnv.APP_DOMAIN
  if (!appDomain) {
    throw new Error('APP_DOMAIN must be set in backend .env')
  }
  return `https://${appDomain}`
}

function timestampForFilename(): string {
  return new Date().toISOString().replace(/[:.]/g, '-')
}

function resolveTargetUrl(target: string, baseUrl: string): string {
  return new URL(target, baseUrl).toString()
}

function isAuthBlocker(url: string): boolean {
  const parsedUrl = new URL(url)
  return parsedUrl.pathname === '/login' || parsedUrl.pathname === '/session-check'
}

function normalizePathname(pathname: string): string {
  if (pathname === '/') {
    return pathname
  }
  return pathname.replace(/\/$/, '')
}

function hasRouteMismatch(requestedUrl: string, finalUrl: string): boolean {
  const requested = new URL(requestedUrl)
  const actual = new URL(finalUrl)
  return (
    requested.origin === actual.origin &&
    normalizePathname(requested.pathname) !== normalizePathname(actual.pathname)
  )
}

async function authenticate(page: Page): Promise<void> {
  const username = process.env.E2E_TEST_USERNAME
  const password = process.env.E2E_TEST_PASSWORD

  if (!username || !password) {
    throw new Error(
      'E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env\n' +
        'These are the same credentials used for e2e tests.',
    )
  }

  console.log('Authenticating...')
  await page.goto('/login')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await page.waitForURL('**/kanban')
  console.log('Authenticated successfully')
}

async function collectDiagnostics(
  page: Page,
  response: Response | null,
  outputPath: string,
  diagnosticsPath: string,
  failedResponses: PageDiagnostics['failedResponses'],
  requestedUrl: string,
): Promise<PageDiagnostics> {
  const body = await page
    .locator('body')
    .innerText({ timeout: 5000 })
    .catch(() => '')
  const headings = await page
    .locator('h1,h2,h3,[role=heading]')
    .evaluateAll((elements) =>
      elements
        .map((element) => element.textContent?.trim())
        .filter((text): text is string => Boolean(text)),
    )
    .catch(() => [])
  const finalUrl = page.url()

  return {
    screenshot: outputPath,
    diagnostics: diagnosticsPath,
    initialStatus: response?.status() ?? null,
    finalUrl,
    title: await page.title(),
    loginDetected: isAuthBlocker(finalUrl),
    routeMismatch: hasRouteMismatch(requestedUrl, finalUrl),
    headings,
    failedResponses,
    bodyPreview: body.slice(0, 800),
  }
}

async function captureSingleScreenshot(options: CliOptions): Promise<void> {
  if (!options.url) {
    throw new Error('--url is required for single screenshot mode')
  }

  const baseUrl = getBaseUrl()
  const targetUrl = resolveTargetUrl(options.url, baseUrl)
  const outputPath =
    options.output ?? path.join('/tmp', `docketworks-screenshot-${timestampForFilename()}.png`)
  const diagnosticsPath = `${outputPath}.json`

  await fs.mkdir(path.dirname(outputPath), { recursive: true })

  console.log(`Using base URL: ${baseUrl}`)
  console.log(`Capturing single page: ${targetUrl}`)

  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    baseURL: baseUrl,
  })
  const failedResponses: PageDiagnostics['failedResponses'] = []
  context.on('response', (response) => {
    if (response.status() >= 400) {
      failedResponses.push({
        method: response.request().method(),
        status: response.status(),
        url: response.url(),
      })
    }
  })
  const page = await context.newPage()

  try {
    await authenticate(page)
    failedResponses.length = 0
    const response = await page.goto(targetUrl, {
      waitUntil: 'networkidle',
      timeout: 45000,
    })

    if (options.waitFor) {
      console.log(`Waiting for: ${options.waitFor}`)
      await page.waitForSelector(options.waitFor, { timeout: 15000 })
    }

    await page.waitForTimeout(500)
    await page.screenshot({
      path: outputPath,
      fullPage: options.fullPage,
    })

    const diagnostics = await collectDiagnostics(
      page,
      response,
      outputPath,
      diagnosticsPath,
      failedResponses,
      targetUrl,
    )
    await fs.writeFile(diagnosticsPath, JSON.stringify(diagnostics, null, 2))

    console.log(`Screenshot saved to: ${outputPath}`)
    console.log(`Diagnostics saved to: ${diagnosticsPath}`)

    if (diagnostics.loginDetected) {
      throw new Error(
        `Target page was not reached; browser ended on an auth/login state: ${diagnostics.finalUrl}`,
      )
    }
    if (diagnostics.routeMismatch) {
      throw new Error(
        `Target route was not reached; requested ${targetUrl} but ended on ${diagnostics.finalUrl}`,
      )
    }
  } finally {
    await browser.close()
  }
}

async function captureScreenshots(): Promise<void> {
  // Ensure output directory exists
  await fs.mkdir(OUTPUT_DIR, { recursive: true })

  const baseUrl = getBaseUrl()
  console.log(`Using base URL: ${baseUrl}`)

  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    baseURL: baseUrl,
  })
  const page = await context.newPage()

  // Authenticate first
  await authenticate(page)

  const manifest: Record<string, { path: string; description: string }> = {}
  const errors: string[] = []

  for (const def of SCREENSHOTS) {
    console.log(`\nCapturing: ${def.id}`)
    console.log(`  Route: ${def.route}`)

    try {
      // Navigate to the route
      await page.goto(def.route)

      // Wait for the specified selector if provided
      if (def.waitFor) {
        console.log(`  Waiting for: ${def.waitFor}`)
        await page.waitForSelector(def.waitFor, { timeout: 15000 })
      }

      // Run any preparation steps
      if (def.prepare) {
        console.log('  Running prepare function...')
        await def.prepare(page)
      }

      // Small delay for animations to settle
      await page.waitForTimeout(500)

      // Capture the screenshot
      const filename = `${def.id}.png`
      const filepath = path.join(OUTPUT_DIR, filename)

      await page.screenshot({
        path: filepath,
        fullPage: def.fullPage ?? false,
        clip: def.clip,
      })

      console.log(`  Saved: ${filename}`)

      // Add to manifest
      manifest[def.id] = {
        path: `/screenshots/${filename}`,
        description: def.description,
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      console.error(`  ERROR: ${message}`)
      errors.push(`${def.id}: ${message}`)
    }
  }

  // Write manifest for content authors
  await fs.writeFile(MANIFEST_PATH, JSON.stringify(manifest, null, 2))

  await browser.close()

  // Summary
  console.log('\n' + '='.repeat(50))
  console.log(`Captured ${Object.keys(manifest).length}/${SCREENSHOTS.length} screenshots`)
  console.log(`Manifest written to: ${MANIFEST_PATH}`)

  if (errors.length > 0) {
    console.log('\nErrors:')
    errors.forEach((e) => console.log(`  - ${e}`))
  }

  console.log('\nScreenshots saved to: ' + OUTPUT_DIR)
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2))
  if (options.url) {
    await captureSingleScreenshot(options)
  } else {
    await captureScreenshots()
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error('Fatal error:', error)
    process.exit(1)
  })
}
