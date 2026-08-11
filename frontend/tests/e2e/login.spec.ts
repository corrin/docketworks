import type { Page } from '@playwright/test'

import { e2eCredentials, expect, test } from './fixtures/auth'
import { UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR } from './fixtures/authConsoleErrors'
import { autoId } from './helpers'

const GATEWAY_CONSOLE_ERROR = 'Failed to load resource: the server responded with a status of 502'
const AXIOS_GATEWAY_CONSOLE_ERROR = 'AxiosError: Request failed with status code 502'

async function replaceAuthCookie(
  page: Page,
  name: 'access_token' | 'refresh_token',
  value: string,
): Promise<void> {
  await page.context().addCookies([
    {
      name,
      value,
      url: new URL(page.url()).origin,
      sameSite: 'Lax',
    },
  ])
}

test.describe('login flow', () => {
  test.describe('deliberately unauthenticated', () => {
    // These tests reach the app unauthenticated outside the fixture login
    // window, so the pre-auth GET /me 401 (and the bad-credentials token 401,
    // which Chrome reports with the same console text) is the point of the
    // test, not a bug.
    test.use({ expectedConsoleErrors: [UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR] })

    test('unauthenticated visit to / redirects to /login', async ({ page }) => {
      await page.goto('/')
      await expect(page).toHaveURL(/\/login/)
      await expect(autoId(page, 'LoginView-username')).toBeVisible()
    })

    test('bad credentials show an error', async ({ page }) => {
      await page.goto('/login')

      await autoId(page, 'LoginView-username').fill('nobody@example.com')
      await autoId(page, 'LoginView-password').fill('definitely-wrong-password')
      await autoId(page, 'LoginView-submit').click()

      await expect(autoId(page, 'LoginView-error')).toBeVisible()
      await expect(page).toHaveURL(/\/login/)
    })

    test('malicious redirect param is ignored after login', async ({ page }) => {
      // Open-redirect guard: absolute and protocol-relative destinations are
      // dropped; login lands on the default in-app page on the same origin.
      await page.goto('/login?redirect=https%3A%2F%2Fevil.example%2Ffake')
      const creds = e2eCredentials()
      await autoId(page, 'LoginView-username').fill(creds.username)
      await autoId(page, 'LoginView-password').fill(creds.password)
      await autoId(page, 'LoginView-submit').click()
      await expect(page).toHaveURL(/\/kanban/)
    })

    test('logout returns to login', async ({ authenticatedPage: page }) => {
      await autoId(page, 'AppNavbar-logout').click()
      await expect(page).toHaveURL(/\/login/)

      // The session is really gone: a fresh visit to the app is gated again.
      await page.goto('/')
      await expect(page).toHaveURL(/\/login/)
      await expect(autoId(page, 'LoginView-username')).toBeVisible()
    })
  })

  test('good credentials land on the app shell', async ({ authenticatedPage: page }) => {
    await expect(page).toHaveURL(/\/kanban/)
    await expect(autoId(page, 'kanban-page')).toBeVisible()
    await expect(autoId(page, 'AppNavbar-logout')).toBeVisible()
  })

  test.describe('session recovery', () => {
    test.use({
      expectedConsoleErrors: [
        UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR,
        GATEWAY_CONSOLE_ERROR,
        AXIOS_GATEWAY_CONSOLE_ERROR,
      ],
    })

    test('stale access with a valid refresh remains on the protected page', async ({
      authenticatedPage: page,
    }) => {
      await replaceAuthCookie(page, 'access_token', 'stale-access-token')
      const refreshResponse = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/accounts/token/refresh/' &&
          response.request().method() === 'POST',
      )

      await page.reload()

      expect((await refreshResponse).status()).toBe(200)
      await expect(page).toHaveURL(/\/kanban/)
      await expect(autoId(page, 'kanban-page')).toBeVisible()
      const access = (await page.context().cookies()).find(
        (cookie) => cookie.name === 'access_token',
      )
      expect(access?.value).not.toBe('stale-access-token')
    })

    test('unverifiable access and refresh are cleared before login', async ({
      authenticatedPage: page,
    }) => {
      await replaceAuthCookie(page, 'access_token', 'stale-access-token')
      await replaceAuthCookie(page, 'refresh_token', 'stale-refresh-token')

      await page.reload()

      await expect(page).toHaveURL(/\/login\?redirect=/)
      await expect(autoId(page, 'LoginView-username')).toBeVisible()
      const cookieNames = (await page.context().cookies()).map((cookie) => cookie.name)
      expect(cookieNames).not.toContain('access_token')
      expect(cookieNames).not.toContain('refresh_token')
    })

    test('session-probe outage offers retry and preserves the destination', async ({
      authenticatedPage: page,
    }) => {
      await page.route('**/api/accounts/me/', async (route) => {
        await route.fulfill({ status: 502, body: '' })
      })

      await page.reload()

      await expect(autoId(page, 'SessionCheck-page')).toBeVisible()
      await expect(page).toHaveURL(/\/session-check\?redirect=%2Fkanban/)
      await page.unroute('**/api/accounts/me/')
      await page.getByRole('button', { name: 'Retry' }).click()
      await expect(page).toHaveURL(/\/kanban/)
      await expect(autoId(page, 'kanban-page')).toBeVisible()
    })

    test('shell-data outage renders a recoverable route error', async ({
      authenticatedPage: page,
    }) => {
      await page.route('**/api/company-defaults/', async (route) => {
        await route.fulfill({ status: 502, body: '' })
      })

      await page.reload()

      await expect(autoId(page, 'RouteError-page')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Connection interrupted' })).toBeVisible()
      await page.unroute('**/api/company-defaults/')
      await page.getByRole('button', { name: 'Retry' }).click()
      await expect(autoId(page, 'kanban-page')).toBeVisible()
    })
  })
})
