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

/** `animations: 'disabled'` fast-forwards the entrance animations, so the
    picture is the settled screen rather than a frame from the middle of one. */
async function attachScreenshot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await testInfo.attach(name, {
    body: await page.screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  })
}

test.use({ loginRole: 'workshop' })

test.describe('workshop login on a phone', () => {
  test.describe('signed out', () => {
    // These tests reach the app signed out outside the fixture's login
    // window: the pre-auth GET /me 401, the bad-credentials token 401 and the
    // session probes after signing out are the point of them, not a bug (see
    // login.spec.ts).
    test.use({ expectedConsoleErrors: [UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR] })

    test('the login form fits the phone and asks for an email', async ({ page }, testInfo) => {
      await page.goto('/login')
      const username = autoId(page, 'LoginView-username')
      await expect(username).toBeVisible()

      await expect(username).toHaveAttribute('type', 'email')
      const usernameFontPx = await fontSizePx(page, 'LoginView-username')
      const passwordFontPx = await fontSizePx(page, 'LoginView-password')
      testInfo.annotations.push({
        type: 'login input font size',
        description: `username ${usernameFontPx}px, password ${passwordFontPx}px`,
      })
      expect(usernameFontPx).toBeGreaterThanOrEqual(IOS_NO_ZOOM_FONT_PX)
      expect(passwordFontPx).toBeGreaterThanOrEqual(IOS_NO_ZOOM_FONT_PX)
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

    test('signs out and the app is gated again', async ({ authenticatedPage: page }) => {
      await autoId(page, 'AppNavbar-logout').tap()
      await expect(page).toHaveURL(/\/login/)

      await page.goto('/')
      await expect(page).toHaveURL(/\/login/)
      await expect(autoId(page, 'LoginView-username')).toBeVisible()
    })
  })

  // No console-error allowance here: a 401 or 403 while signed in is the
  // workshop login reaching something it may not, which is what this proves
  // does not happen.
  test('signs in and reaches My time from the navbar', async ({
    authenticatedPage: page,
  }, testInfo) => {
    await test.step('lands on the board without the office controls', async () => {
      await expect(page).toHaveURL(/\/kanban/)
      await expect(autoId(page, 'kanban-page')).toBeVisible()
      await expect(autoId(page, 'AppNavbar-create-job')).toHaveCount(0)
      const headerHeightPx = await page
        .locator('header')
        .first()
        .evaluate((header) => Math.round(header.getBoundingClientRect().height))
      testInfo.annotations.push({
        type: 'header height',
        description: `${headerHeightPx}px of a ${page.viewportSize()?.height}px viewport`,
      })
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
      // The panel fades out before it leaves the page; the picture below is
      // of the page it was covering, so wait for it to go.
      await expect(autoId(page, 'AppNavbar-timesheets-menu-content')).toHaveCount(0)
      await expect(page.getByRole('heading', { name: 'Workshop timesheets' })).toBeVisible()
      await expect(autoId(page, 'WorkshopTimesheetCalendar')).toBeVisible()
      await attachScreenshot(page, testInfo, 'my-time')
      await expectNoHorizontalOverflow(page)
    })
  })
})
