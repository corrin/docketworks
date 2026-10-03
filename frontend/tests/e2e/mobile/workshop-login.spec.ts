/**
 * Workshop (shop-floor) staff use the app from their phones. This proves the
 * first thing they must be able to do there: sign in, find their timesheet,
 * and sign out. It runs on the phone projects only (playwright.config.ts) and
 * as the workshop login, which is neither office staff nor a superuser — so
 * any office-only request the shell makes on their behalf fails the test as
 * an unexpected console error.
 */
import type { Page, TestInfo } from '@playwright/test'

import { e2eCredentials, expect, test } from '../fixtures/auth'
import { UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR } from '../fixtures/authConsoleErrors'
import { autoId } from '../helpers'

/** iOS Safari zooms the page when a focused input's text is smaller than this. */
const IOS_NO_ZOOM_FONT_PX = 16

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, 'the page must not scroll sideways on a phone').toBeLessThanOrEqual(0)
}

async function fontSizePx(page: Page, automationId: string): Promise<number> {
  return autoId(page, automationId).evaluate((element) =>
    Number.parseFloat(getComputedStyle(element).fontSize),
  )
}

async function attachScreenshot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' })
}

test.use({ loginRole: 'workshop' })

test.describe('workshop login on a phone', () => {
  test.describe('before signing in', () => {
    // The pre-auth GET /me 401 and the bad-credentials token 401 are the
    // point of these tests, not a bug (see login.spec.ts).
    test.use({ expectedConsoleErrors: [UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR] })

    test('the login form fits the phone and asks for an email', async ({ page }, testInfo) => {
      await page.goto('/login')
      const username = autoId(page, 'LoginView-username')
      await expect(username).toBeVisible()

      await expect(username).toHaveAttribute('type', 'email')
      expect(await fontSizePx(page, 'LoginView-username')).toBeGreaterThanOrEqual(
        IOS_NO_ZOOM_FONT_PX,
      )
      expect(await fontSizePx(page, 'LoginView-password')).toBeGreaterThanOrEqual(
        IOS_NO_ZOOM_FONT_PX,
      )
      await expectNoHorizontalOverflow(page)
      await attachScreenshot(page, testInfo, 'login')
    })

    test('a wrong password shows the error', async ({ page }) => {
      await page.goto('/login')

      await autoId(page, 'LoginView-username').fill(e2eCredentials('workshop').username)
      await autoId(page, 'LoginView-password').fill('definitely-wrong-password')
      await autoId(page, 'LoginView-submit').tap()

      await expect(autoId(page, 'LoginView-error')).toBeVisible()
      await expect(page).toHaveURL(/\/login/)
    })
  })

  test('signs in, reaches My time from the navbar and signs out', async ({
    authenticatedPage: page,
  }, testInfo) => {
    await test.step('lands on the board without the office controls', async () => {
      await expect(page).toHaveURL(/\/kanban/)
      await expect(autoId(page, 'kanban-page')).toBeVisible()
      await expect(autoId(page, 'AppNavbar-create-job')).toHaveCount(0)
      await attachScreenshot(page, testInfo, 'kanban')
      await expectNoHorizontalOverflow(page)
    })

    await test.step('the Timesheets menu offers My time and nothing it cannot open', async () => {
      await autoId(page, 'AppNavbar-timesheets-menu').tap()
      await expect(autoId(page, 'AppNavbar-my-time')).toBeVisible()
      await attachScreenshot(page, testInfo, 'timesheets-menu')
      await expect(autoId(page, 'AppNavbar-daily-timesheets')).toHaveCount(0)
      await expect(autoId(page, 'AppNavbar-weekly-timesheets')).toHaveCount(0)
      await expect(autoId(page, 'AppNavbar-leave')).toHaveCount(0)
    })

    await test.step('My time opens', async () => {
      await autoId(page, 'AppNavbar-my-time').tap()
      await expect(page).toHaveURL(/\/timesheets\/my-time/)
      await expect(page.getByRole('heading', { name: 'Workshop timesheets' })).toBeVisible()
      await attachScreenshot(page, testInfo, 'my-time')
      await expectNoHorizontalOverflow(page)
    })

    await test.step('signs out, and the app is gated again', async () => {
      await autoId(page, 'AppNavbar-logout').tap()
      await expect(page).toHaveURL(/\/login/)

      await page.goto('/')
      await expect(page).toHaveURL(/\/login/)
      await expect(autoId(page, 'LoginView-username')).toBeVisible()
    })
  })
})
