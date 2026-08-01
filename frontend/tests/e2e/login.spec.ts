import { e2eCredentials, expect, test } from './fixtures/auth'
import { autoId } from './helpers'

test.describe('login flow', () => {
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

  test('good credentials land on the app shell', async ({ authenticatedPage: page }) => {
    await expect(page).toHaveURL(/\/kanban/)
    await expect(autoId(page, 'kanban-page')).toBeVisible()
    await expect(autoId(page, 'AppNavbar-logout')).toBeVisible()
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
