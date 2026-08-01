/**
 * Auth fixture, minimally ported from v1 tests/fixtures/auth.ts: logs in via
 * the UI with env-provided credentials and hands the test an authenticated
 * page. (v1's console-error guard, network logging and shared-job fixtures
 * port with their features in later slices.)
 */
import { expect, type Page, type Response, test as base } from '@playwright/test'

import { autoId, INFINITE_TIMEOUT, waitForCurrentUrl } from '../helpers'

export const LOGIN_TOKEN_PATH = '/api/accounts/token/'
export const LOGIN_ME_PATH = '/api/accounts/me/'

export function e2eCredentials(): { username: string; password: string } {
  const username = process.env.E2E_TEST_USERNAME
  const password = process.env.E2E_TEST_PASSWORD

  if (!username || !password) {
    throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
  }

  return { username, password }
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

export async function authenticateViaLoginPage(
  page: Page,
  username: string,
  password: string,
): Promise<void> {
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
  // The /me waiter must skip the expected pre-auth 401 session check and
  // resolve on the authenticated response.
  const meResponsePromise = waitForLoginResponse(
    page,
    LOGIN_ME_PATH,
    'GET',
    (response) => response.status() === 200,
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

  await meResponsePromise
  await waitForCurrentUrl(page, /\/kanban\/?(?:[?#].*)?$/)
}

type AuthFixtures = {
  authenticatedPage: Page
}

export const test = base.extend<AuthFixtures>({
  authenticatedPage: async ({ page }, use) => {
    const { username, password } = e2eCredentials()

    await base.step('authenticatedPage: login', async () => {
      await authenticateViaLoginPage(page, username, password)
    })

    await use(page)
  },
})

export { expect }
