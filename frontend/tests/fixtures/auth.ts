import { test as base, expect, type Page, type Response } from '@playwright/test'
import {
  dismissToasts,
  autoId,
  enableNetworkLogging,
  expectStepUnder,
  INFINITE_TIMEOUT,
  submitJobAndWaitForCreatedJob,
  TEST_COMPANY_NAME,
  waitForCurrentUrl,
} from './helpers'
import {
  createLoginSessionCheckConsoleAllowance,
  LOGIN_ME_PATH,
  type CapturedBrowserError,
} from '@/utils/authConsoleErrors'

// Define fixture types
type AuthFixtures = {
  sessionCheckConsoleAllowance: ReturnType<typeof createLoginSessionCheckConsoleAllowance>
  authenticatedPage: Page
  /**
   * Patterns for console errors a test deliberately triggers (string = substring,
   * RegExp = test). Set via `test.use({ expectedConsoleErrors: [...] })`. Any
   * browser console error or uncaught page exception NOT matching a pattern
   * fails the test — every console.error must toast or throw (rule 30).
   */
  expectedConsoleErrors: Array<string | RegExp>
}

type WorkerFixtures = {
  // Worker-scoped fixtures for shared test data
  sharedEditJobUrl: string
}

const SHARED_EDIT_JOB_BUDGET_MS = {
  navigateToCreatePage: 2500,
  searchAndSelectCompany: 1500,
  fillJobDetails: 1000,
  contactSelection: 2500,
  submitAndRedirect: 3500,
} as const

const LOGIN_TOKEN_PATH = '/api/accounts/token/'
function isExpectedBrowserError(text: string, patterns: ReadonlyArray<string | RegExp>): boolean {
  return patterns.some((pattern) =>
    typeof pattern === 'string' ? text.includes(pattern) : pattern.test(text),
  )
}

function waitForLoginResponse(page: Page, path: string, method: 'GET' | 'POST'): Promise<Response> {
  return page.waitForResponse(
    (candidate) => {
      const url = new URL(candidate.url())
      return url.pathname === path && candidate.request().method() === method
    },
    { timeout: INFINITE_TIMEOUT },
  )
}

async function responseDiagnostics(label: string, response?: Response): Promise<string> {
  if (!response) {
    return `${label}: no response observed`
  }

  let body = '<unavailable>'
  try {
    body = await response.text()
  } catch {
    body = '<body could not be read>'
  }

  const bodyPreview = body.length > 500 ? `${body.slice(0, 500)}...` : body
  const url = new URL(response.url())
  return [
    `${label}: ${response.request().method()} ${url.pathname} -> ${response.status()} ${response.statusText()}`,
    `${label} body: ${bodyPreview || '<empty>'}`,
  ].join('\n')
}

async function loginPageDiagnostics(page: Page): Promise<string> {
  const submitButton = autoId(page, 'LoginView-submit')
  const errorMessage = autoId(page, 'LoginView-error')

  const readState = async <T>(reader: () => Promise<T>, fallback: T): Promise<T> => {
    try {
      return await reader()
    } catch {
      return fallback
    }
  }

  const buttonCount = await readState(() => submitButton.count(), 0)
  const buttonText =
    buttonCount > 0 ? await readState(() => submitButton.innerText(), '<unreadable>') : '<missing>'
  const buttonVisible =
    buttonCount > 0 ? await readState(() => submitButton.isVisible(), false) : false
  const buttonEnabled =
    buttonCount > 0 ? await readState(() => submitButton.isEnabled(), false) : false
  const visibleError =
    (await readState(() => errorMessage.count(), 0)) > 0
      ? await readState(() => errorMessage.innerText(), '')
      : ''

  return [
    `current URL: ${page.url()}`,
    `submit button: count=${buttonCount} visible=${buttonVisible} enabled=${buttonEnabled} text=${JSON.stringify(buttonText)}`,
    `visible login error: ${visibleError ? JSON.stringify(visibleError) : '<none>'}`,
  ].join('\n')
}

async function authenticateViaLoginPage(
  page: Page,
  username: string,
  password: string,
  startSessionCheckConsoleAllowance: () => () => void = () => () => undefined,
): Promise<void> {
  let tokenResponse: Response | undefined
  let meResponse: Response | undefined
  const stopSessionCheckConsoleAllowance = startSessionCheckConsoleAllowance()

  try {
    await page.goto('/login')

    const usernameInput = autoId(page, 'LoginView-username')
    const passwordInput = autoId(page, 'LoginView-password')
    const submitButton = autoId(page, 'LoginView-submit')

    await expect(usernameInput).toBeVisible()
    await expect(passwordInput).toBeVisible()

    await usernameInput.fill(username)
    await passwordInput.fill(password)

    await expect(submitButton).toBeEnabled()

    const tokenResponsePromise = waitForLoginResponse(page, LOGIN_TOKEN_PATH, 'POST')
    const meResponsePromise = waitForLoginResponse(page, LOGIN_ME_PATH, 'GET')
    void tokenResponsePromise.catch(() => undefined)
    void meResponsePromise.catch(() => undefined)

    await submitButton.click()

    tokenResponse = await tokenResponsePromise
    if (!tokenResponse.ok()) {
      throw new Error(await responseDiagnostics('token response', tokenResponse))
    }

    meResponse = await meResponsePromise
    if (!meResponse.ok()) {
      throw new Error(await responseDiagnostics('current-user response', meResponse))
    }

    await waitForCurrentUrl(page, /\/kanban\/?(?:[?#].*)?$/)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    throw new Error(
      [
        `E2E login did not reach /kanban: ${message}`,
        await loginPageDiagnostics(page),
        await responseDiagnostics('token response', tokenResponse),
        await responseDiagnostics('current-user response', meResponse),
      ].join('\n'),
    )
  } finally {
    stopSessionCheckConsoleAllowance()
  }
}

export const test = base.extend<AuthFixtures, WorkerFixtures>({
  expectedConsoleErrors: [[], { option: true }],
  sessionCheckConsoleAllowance: async ({}, use) => {
    await use(createLoginSessionCheckConsoleAllowance())
  },

  // Every test's page fails on unexpected browser console errors and uncaught
  // page exceptions. authenticatedPage wraps this fixture, so login is covered too.
  page: async ({ page, expectedConsoleErrors, sessionCheckConsoleAllowance }, use) => {
    const captured: CapturedBrowserError[] = []
    page.on('response', (response) => {
      const url = new URL(response.url())
      sessionCheckConsoleAllowance.recordResponse({
        pathname: url.pathname,
        method: response.request().method(),
        status: response.status(),
      })
    })
    page.on('console', (message) => {
      if (message.type() === 'error') {
        captured.push({ kind: 'console', text: message.text(), capturedAt: Date.now() })
      } else {
        // other console levels are out of scope for this guard
      }
    })
    page.on('pageerror', (error) => {
      captured.push({ kind: 'pageerror', text: error.message, capturedAt: Date.now() })
    })

    await use(page)

    const unexpected = captured.filter((entry) => {
      if (sessionCheckConsoleAllowance.consumeIfExpected(entry)) {
        return false
      }
      return !isExpectedBrowserError(entry.text, expectedConsoleErrors)
    })
    if (unexpected.length > 0) {
      throw new Error(
        [
          `Browser emitted ${unexpected.length} unexpected error(s) during this test.`,
          'Every console.error must toast or throw (rule 30) — fix the cause, or if this',
          'test deliberately triggers the error, allow it via',
          'test.use({ expectedConsoleErrors: [...] }).',
          ...unexpected.map((entry) => `- [${entry.kind}] ${entry.text}`),
        ].join('\n'),
      )
    } else {
      // no unexpected browser errors — nothing to report
    }
  },

  authenticatedPage: async ({ page, sessionCheckConsoleAllowance }, use, testInfo) => {
    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD

    if (!username || !password) {
      throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
    }

    // Enable network logging for all tests
    enableNetworkLogging(page, testInfo.title)

    await base.step('authenticatedPage: login', async () => {
      await authenticateViaLoginPage(
        page,
        username,
        password,
        sessionCheckConsoleAllowance.startLoginWindow,
      )
    })

    // Enable debug logging if DEBUG env var is set
    if (process.env.DEBUG === 'true') {
      await page.evaluate(() => localStorage.setItem('debug', 'true'))
    }

    // Pass the authenticated page to the test
    await use(page)
  },

  // Worker-scoped fixture that creates a job once per worker
  // This allows running individual tests that depend on a shared job
  sharedEditJobUrl: [
    async ({ browser }, use) => {
      const username = process.env.E2E_TEST_USERNAME
      const password = process.env.E2E_TEST_PASSWORD

      if (!username || !password) {
        throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
      }

      // Create a new context and page for job creation
      const context = await browser.newContext()
      const page = await context.newPage()

      await base.step('sharedEditJobUrl: login', async () => {
        await authenticateViaLoginPage(page, username, password)
      })

      // Create the job using the helper (but with fixed_price for edit tests)
      const timestamp = Date.now()
      const jobName = `[TEST] Edit Job ${timestamp}`

      await expectStepUnder(
        'sharedEditJobUrl: navigate to create job page',
        SHARED_EDIT_JOB_BUDGET_MS.navigateToCreatePage,
        async () => {
          await autoId(page, 'AppNavbar-create-job').click()
          await page.waitForURL('**/jobs/create')
          await page.waitForLoadState('networkidle')
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: search and select company',
        SHARED_EDIT_JOB_BUDGET_MS.searchAndSelectCompany,
        async () => {
          const companyInput = autoId(page, 'CompanyLookup-input')
          await companyInput.waitFor({ timeout: 10000 })
          await companyInput.fill('ABC')
          await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
          await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: fill job details',
        SHARED_EDIT_JOB_BUDGET_MS.fillJobDetails,
        async () => {
          await autoId(page, 'JobCreateView-name-input').fill(jobName)
          await autoId(page, 'JobCreateView-estimated-materials').fill('1000')
          await autoId(page, 'JobCreateView-estimated-time').fill('8')
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: select or create contact',
        SHARED_EDIT_JOB_BUDGET_MS.contactSelection,
        async () => {
          await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
          await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

          const selectButtons = autoId(page, 'PersonSelectionModal-select-button')
          const selectButtonCount = await selectButtons.count()

          if (selectButtonCount > 0) {
            await selectButtons.first().click()
          } else {
            const submitButton = autoId(page, 'PersonSelectionModal-submit')
            await autoId(page, 'PersonSelectionModal-name-input').fill(`[TEST] Person ${timestamp}`)
            await autoId(page, 'PersonSelectionModal-email-input').fill(
              `test${timestamp}@example.com`,
            )
            await submitButton.click()
          }

          await autoId(page, 'PersonSelectionModal-container').waitFor({
            state: 'hidden',
            timeout: 10000,
          })
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: submit fixed price job',
        SHARED_EDIT_JOB_BUDGET_MS.submitAndRedirect,
        async () => {
          await autoId(page, 'JobCreateView-pricing-method').selectOption('fixed_price')
          await dismissToasts(page)
          await submitJobAndWaitForCreatedJob(page, 'quote')
        },
      )

      const jobUrl = page.url()
      console.log(`[Fixture] Created shared edit job at: ${jobUrl}`)

      await context.close()

      // Provide the URL to tests
      await use(jobUrl)
    },
    { scope: 'worker' }, // Share across all tests in the worker
  ],
})

export { expect }
