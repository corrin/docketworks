/**
 * Log in through the UI with environment-provided credentials and hand the
 * test an authenticated page. Every test's page fails on unexpected browser
 * console errors and uncaught page exceptions, and all API traffic is
 * wire-size-guarded via enableNetworkLogging.
 */
import { expect, type Page, type Response, test as base } from '@playwright/test'

import {
  autoId,
  createTestJob,
  enableNetworkLogging,
  INFINITE_TIMEOUT,
  waitForCurrentUrl,
} from '../helpers'
import {
  createLoginSessionCheckConsoleAllowance,
  isLoginCompletionResponse,
  LOGIN_ME_PATH,
  type CapturedBrowserError,
} from './authConsoleErrors'
import { browserDebugGlob, installBrowserDebugForwarder } from './debug-forwarder'

export const LOGIN_TOKEN_PATH = '/api/accounts/token/'

export function e2eCredentials(): { username: string; password: string } {
  const username = process.env.E2E_TEST_USERNAME
  const password = process.env.E2E_TEST_PASSWORD

  if (!username || !password) {
    throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
  }

  return { username, password }
}

function isExpectedBrowserError(text: string, patterns: ReadonlyArray<string | RegExp>): boolean {
  return patterns.some((pattern) =>
    typeof pattern === 'string' ? text.includes(pattern) : pattern.test(text),
  )
}

function waitForLoginResponse(
  page: Page,
  path: string,
  method: 'GET' | 'POST',
  accept: (response: Response) => boolean = () => true,
): Promise<Response> {
  return page.waitForResponse(
    (candidate) => {
      const url = new URL(candidate.url())
      return url.pathname === path && candidate.request().method() === method && accept(candidate)
    },
    { timeout: INFINITE_TIMEOUT },
  )
}

// Adapts a Playwright Response to the login-completion decision — see
// isLoginCompletionResponse for why the waiter must skip the pre-auth 401.
function isAuthenticatedMeResponse(response: Response): boolean {
  return isLoginCompletionResponse({
    method: response.request().method(),
    pathname: new URL(response.url()).pathname,
    status: response.status(),
  })
}

export async function authenticateViaLoginPage(
  page: Page,
  username: string,
  password: string,
  startSessionCheckConsoleAllowance: () => () => void,
): Promise<void> {
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
    const meResponsePromise = waitForLoginResponse(
      page,
      LOGIN_ME_PATH,
      'GET',
      isAuthenticatedMeResponse,
    )
    void tokenResponsePromise.catch(() => undefined)
    void meResponsePromise.catch(() => undefined)

    await submitButton.click()

    const tokenResponse = await tokenResponsePromise
    if (!tokenResponse.ok()) {
      throw new Error(
        `token response: POST ${LOGIN_TOKEN_PATH} -> ${tokenResponse.status()} ${tokenResponse.statusText()}`,
      )
    }

    const meResponse = await meResponsePromise
    if (!meResponse.ok()) {
      throw new Error(
        `current-user response: GET ${LOGIN_ME_PATH} -> ${meResponse.status()} ` +
          `${meResponse.statusText()}\n${await meResponse.text()}`,
      )
    }

    await waitForCurrentUrl(page, /\/kanban\/?(?:[?#].*)?$/)
  } finally {
    stopSessionCheckConsoleAllowance()
  }
}

type AuthFixtures = {
  sessionCheckConsoleAllowance: ReturnType<typeof createLoginSessionCheckConsoleAllowance>
  authenticatedPage: Page
  /**
   * Patterns for console errors a test deliberately triggers (string = substring,
   * RegExp = test). Set via `test.use({ expectedConsoleErrors: [...] })`. Any
   * browser console error or uncaught page exception NOT matching a pattern
   * fails the test — every console.error must toast or throw.
   */
  expectedConsoleErrors: Array<string | RegExp>
}

type WorkerFixtures = {
  /**
   * URL of one fixed-price job (`[TEST] Edit Job <ts>` on the seed company),
   * created once per worker by driving the create-job UI. Specs that only
   * READ the job share it; a spec that mutates shared state (company, person)
   * must create its own job instead.
   */
  sharedEditJobUrl: string
}

export const test = base.extend<AuthFixtures, WorkerFixtures>({
  expectedConsoleErrors: [[], { option: true }],
  // Playwright's fixture API passes dependencies as the first parameter; this
  // fixture has none, but the destructuring slot cannot be omitted or renamed
  // without Playwright misreading the signature.
  // oxlint-disable-next-line no-empty-pattern
  sessionCheckConsoleAllowance: async ({}, use) => {
    await use(createLoginSessionCheckConsoleAllowance())
  },

  // Every test's page fails on unexpected browser console errors and uncaught
  // page exceptions. authenticatedPage wraps this fixture, so login is covered too.
  page: async ({ page, expectedConsoleErrors, sessionCheckConsoleAllowance }, use) => {
    // DEBUG=e2e:<area> enables browser-side `debug` logging (localStorage
    // glob, read by the app at boot) and forwards non-error console output to
    // the test log. Set before the guard below so the forwarder's console
    // listener never touches errors — the guard owns those.
    const debugGlob = browserDebugGlob()
    if (debugGlob !== null) {
      await page.addInitScript((glob) => {
        window.localStorage.setItem('debug', glob)
      }, debugGlob)
    }
    installBrowserDebugForwarder(page)

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
      if (message.type() !== 'error') return
      captured.push({ kind: 'console', text: message.text(), capturedAt: Date.now() })
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
    if (unexpected.length === 0) return
    throw new Error(
      [
        `Browser emitted ${unexpected.length} unexpected error(s) during this test.`,
        'Every console.error must toast or throw — fix the cause, or if this',
        'test deliberately triggers the error, allow it via',
        'test.use({ expectedConsoleErrors: [...] }).',
        ...unexpected.map((entry) => `- [${entry.kind}] ${entry.text}`),
      ].join('\n'),
    )
  },

  authenticatedPage: async ({ page, sessionCheckConsoleAllowance }, use, testInfo) => {
    const { username, password } = e2eCredentials()

    const finishNetworkLogging = enableNetworkLogging(page, testInfo.title)

    try {
      await base.step('authenticatedPage: login', async () => {
        await authenticateViaLoginPage(
          page,
          username,
          password,
          sessionCheckConsoleAllowance.startLoginWindow,
        )
      })

      await use(page)
    } finally {
      await finishNetworkLogging()
    }
  },

  sharedEditJobUrl: [
    async ({ browser }, use) => {
      const { username, password } = e2eCredentials()

      // A throwaway context: the console-error guard lives on the per-test
      // page fixture, so this page has no guard and no login-401 allowance —
      // the no-op starter records that, it does not disable anything.
      const context = await browser.newContext()
      let jobUrl: string
      try {
        const page = await context.newPage()

        await base.step('sharedEditJobUrl: login', async () => {
          await authenticateViaLoginPage(page, username, password, () => () => undefined)
        })

        jobUrl = await base.step('sharedEditJobUrl: create fixed-price job', () =>
          createTestJob(page, 'Edit', {
            jobName: `[TEST] Edit Job ${Date.now()}`,
            materials: '1000',
            time: '8',
            pricing: 'fixed_price',
          }),
        )
      } finally {
        // Closed on failure too, or a mid-fixture flake leaks the context
        // until worker teardown.
        await context.close()
      }

      await use(jobUrl)
    },
    { scope: 'worker' },
  ],
})

export { expect }
