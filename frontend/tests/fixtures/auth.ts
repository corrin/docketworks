import { test as base, expect, type Page, type Response } from '@playwright/test'
import {
  dismissToasts,
  autoId,
  enableNetworkLogging,
  expectStepUnder,
  submitJobAndWaitForCreatedJob,
  TEST_CLIENT_NAME,
  waitForCurrentUrl,
} from './helpers'

// Define fixture types
type AuthFixtures = {
  authenticatedPage: Page
}

type WorkerFixtures = {
  // Worker-scoped fixtures for shared test data
  sharedEditJobUrl: string
}

const SHARED_EDIT_JOB_BUDGET_MS = {
  navigateToCreatePage: 2500,
  searchAndSelectClient: 1500,
  fillJobDetails: 1000,
  contactSelection: 2500,
  submitAndRedirect: 3500,
} as const

const LOGIN_TOKEN_PATH = '/api/accounts/token/'
const LOGIN_ME_PATH = '/api/accounts/me/'

function waitForLoginResponse(page: Page, path: string, method: 'GET' | 'POST'): Promise<Response> {
  return page.waitForResponse(
    (candidate) => {
      const url = new URL(candidate.url())
      return url.pathname === path && candidate.request().method() === method
    },
    { timeout: 0 },
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
  const submitButton = page.locator('form button[type="submit"]').first()
  const errorMessage = page.locator('.text-red-700').first()

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
): Promise<void> {
  let tokenResponse: Response | undefined
  let meResponse: Response | undefined

  try {
    const initialSessionCheckPromise = waitForLoginResponse(page, LOGIN_ME_PATH, 'GET')
    void initialSessionCheckPromise.catch(() => undefined)
    await page.goto('/login')
    await initialSessionCheckPromise

    await page.locator('#username').fill(username)
    await page.locator('#password').fill(password)

    const submitButton = page.locator('form button[type="submit"]').first()
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
  }
}

export const test = base.extend<AuthFixtures, WorkerFixtures>({
  authenticatedPage: async ({ page }, use, testInfo) => {
    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD

    if (!username || !password) {
      throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
    }

    // Enable network logging for all tests
    enableNetworkLogging(page, testInfo.title)

    await base.step('authenticatedPage: login', async () => {
      await authenticateViaLoginPage(page, username, password)
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
        'sharedEditJobUrl: search and select client',
        SHARED_EDIT_JOB_BUDGET_MS.searchAndSelectClient,
        async () => {
          const clientInput = autoId(page, 'ClientLookup-input')
          await clientInput.waitFor({ timeout: 10000 })
          await clientInput.fill('ABC')
          await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
          await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()
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
          await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })
          await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })

          const selectButtons = autoId(page, 'ContactSelectionModal-select-button')
          const selectButtonCount = await selectButtons.count()

          if (selectButtonCount > 0) {
            await selectButtons.first().click()
          } else {
            const submitButton = autoId(page, 'ContactSelectionModal-submit')
            await autoId(page, 'ContactSelectionModal-name-input').fill(
              `[TEST] Contact ${timestamp}`,
            )
            await autoId(page, 'ContactSelectionModal-email-input').fill(
              `test${timestamp}@example.com`,
            )
            await submitButton.click()
          }

          await autoId(page, 'ContactSelectionModal-container').waitFor({
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
