/**
 * The weak-password path end to end: an admin-flagged account is locked to
 * /change-password until a strong password lands, and the forgot-password
 * flow's request and dead-link paths work for an anonymous visitor.
 *
 * The staff member is [TEST]-named and left behind (no staff DELETE —
 * offboarding is date_left; the database restore sweeps the row, same as
 * create-staff). The forgot-password submit uses an address with NO account:
 * the server's fixed 200 sends nothing, so the spec needs no Gmail
 * configuration — the real send is the integration test's job
 * (apps/core/tests/test_gmail_integration.py, ADR 0050).
 */
import { z } from 'zod'

import { expect, test } from './fixtures/auth'
import { UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR } from './fixtures/authConsoleErrors'
import { autoId } from './helpers'

import type { Page } from '@playwright/test'

const timestamp = Date.now()
const firstName = '[TEST] PwGate'
const lastName = `User ${timestamp}`
const email = `e2e.pwgate.${timestamp}@example.com`
const TEMP_PASSWORD = 'Temp-Start-Pass-41!'
const STRONG_PASSWORD = 'Brand-New-Pass-77!'

async function loginAs(page: Page, username: string, password: string): Promise<void> {
  await page.goto('/login')
  await autoId(page, 'LoginView-username').fill(username)
  await autoId(page, 'LoginView-password').fill(password)
  await autoId(page, 'LoginView-submit').click()
}

test.describe.serial('weak password path', () => {
  test.use({
    expectedConsoleErrors: [
      // Deliberate unauthenticated visits (login page, logout) probe /me.
      UNAUTHENTICATED_SESSION_CHECK_CONSOLE_ERROR,
      // The weak change attempt and the dead reset link are 400s by design.
      /the server responded with a status of 400/,
    ],
  })

  test('an admin can create a staff member who must change at next login', async ({
    authenticatedPage: page,
  }) => {
    const response = await page.request.post('/api/accounts/staff/', {
      data: {
        office_email: email,
        first_name: firstName,
        last_name: lastName,
        password: TEMP_PASSWORD,
        password_needs_reset: true,
      },
    })
    expect(response.status()).toBe(201)
    const body = z
      .object({ id: z.string(), password_needs_reset: z.boolean() })
      .parse(await response.json())
    expect(body.password_needs_reset).toBe(true)
  })

  test('a flagged login is locked to the change screen until a strong password lands', async ({
    page,
  }) => {
    await test.step('login lands on the forced change screen', async () => {
      await loginAs(page, email, TEMP_PASSWORD)
      await expect(page).toHaveURL(/\/change-password/)
      await expect(autoId(page, 'ChangePasswordPage-copy')).toHaveText(
        'You must change your password before continuing.',
      )
      await expect(autoId(page, 'ChangePasswordPage-cancel')).toBeHidden()
    })

    await test.step('navigating away bounces back', async () => {
      await page.goto('/kanban')
      await expect(page).toHaveURL(/\/change-password/)
    })

    await test.step('a weak new password is refused with the reason', async () => {
      await autoId(page, 'ChangePasswordPage-current').fill(TEMP_PASSWORD)
      await autoId(page, 'ChangePasswordPage-new').fill('password')
      await autoId(page, 'ChangePasswordPage-confirm').fill('password')
      await autoId(page, 'ChangePasswordPage-submit').click()
      await expect(autoId(page, 'ChangePasswordPage-error')).toContainText('too common')
      await expect(page).toHaveURL(/\/change-password/)
    })

    await test.step('a strong password releases the session', async () => {
      await autoId(page, 'ChangePasswordPage-new').fill(STRONG_PASSWORD)
      await autoId(page, 'ChangePasswordPage-confirm').fill(STRONG_PASSWORD)
      await autoId(page, 'ChangePasswordPage-submit').click()
      await expect(page).toHaveURL(/\/kanban/)
      await expect(autoId(page, 'AppNavbar-logout')).toBeVisible()
    })

    await test.step('the change sticks across a fresh login', async () => {
      await autoId(page, 'AppNavbar-logout').click()
      await expect(page).toHaveURL(/\/login/)
      await loginAs(page, email, STRONG_PASSWORD)
      await expect(page).toHaveURL(/\/kanban/)
      await expect(autoId(page, 'AppNavbar-logout')).toBeVisible()
    })
  })

  test('the forgot-password flow serves an anonymous visitor', async ({ page }) => {
    await test.step('the login page links to the request form', async () => {
      await page.goto('/login')
      await autoId(page, 'login-forgot-password').click()
      await expect(page).toHaveURL(/\/forgot-password/)
    })

    await test.step('submitting shows the fixed confirmation copy', async () => {
      // An address with no account: the fixed 200 sends nothing, and the
      // copy must be indistinguishable from a real send.
      await autoId(page, 'ForgotPasswordPage-email').fill(`e2e.nobody.${timestamp}@example.com`)
      await autoId(page, 'ForgotPasswordPage-submit').click()
      await expect(autoId(page, 'ForgotPasswordPage-sent')).toBeVisible()
    })

    await test.step('a truncated reset link renders the invalid-link state', async () => {
      await page.goto('/reset-password')
      await expect(autoId(page, 'ResetPasswordPage-invalid')).toBeVisible()
    })

    await test.step('a garbage reset link is refused on submit', async () => {
      await page.goto('/reset-password?uid=abc&token=def')
      await autoId(page, 'ResetPasswordPage-new').fill(STRONG_PASSWORD)
      await autoId(page, 'ResetPasswordPage-confirm').fill(STRONG_PASSWORD)
      await autoId(page, 'ResetPasswordPage-submit').click()
      await expect(autoId(page, 'ResetPasswordPage-error')).toHaveText(
        'This reset link is invalid or has expired.',
      )
    })
  })
})
