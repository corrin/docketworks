/**
 * A workshop user who has forgotten their password gets back in from their
 * phone: ask for a reset, open the link from the email, choose a new
 * password, sign in with it. The email is a real send through the company's
 * Google Workspace, read back from the mailbox it lands in, because the loop
 * that matters is the one with the real link in it (KAN-345).
 *
 * The workshop login's address is a plus-address of a real mailbox whose tag
 * names the environment (`E2E_WORKSHOP_USERNAME`, e.g. name+e2e-dev@), so a
 * reset email says which environment sent it and no environment reads
 * another's link; `E2E_RESET_MAILBOX_OWNER` is the Workspace user that mailbox
 * belongs to. Reset emails are left in the mailbox: the read
 * scope cannot delete, and each run only looks at mail newer than itself.
 */
import type { Page } from '@playwright/test'
import { z } from 'zod'

import { runManagePy } from '../../scripts/db-backup-utils'
import { e2eCredentials, expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

const NEW_PASSWORD = 'Phone-Reset-Chosen-58!'
/** iOS Safari zooms the page when a focused input's text is smaller than this. */
const IOS_NO_ZOOM_FONT_PX = 16

const readerOutput = z.object({ link: z.string().nullable() })

function mailboxOwner(): string {
  const owner = process.env.E2E_RESET_MAILBOX_OWNER
  if (!owner) throw new Error('E2E_RESET_MAILBOX_OWNER must be set in .env.test')
  return owner
}

/** The newest reset link emailed to `address` since `since`, or null if none yet. */
function latestResetLink(address: string, since: string): string | null {
  const stdout = runManagePy([
    'e2e_read_reset_link',
    `--to=${address}`,
    `--mailbox=${mailboxOwner()}`,
    `--since=${since}`,
  ])
  const lastLine = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .findLast((line) => line !== '')
  if (lastLine === undefined) throw new Error('e2e_read_reset_link printed nothing')
  return readerOutput.parse(JSON.parse(lastLine)).link
}

async function fontSizePx(page: Page, automationId: string): Promise<number> {
  return autoId(page, automationId).evaluate((element) =>
    Number.parseFloat(getComputedStyle(element).fontSize),
  )
}

/** Signs in from the login screen, where both the reset and signing out leave the user. */
async function signIn(page: Page, username: string, password: string): Promise<void> {
  await expect(page).toHaveURL(/\/login/)
  await autoId(page, 'LoginView-username').fill(username)
  await autoId(page, 'LoginView-password').fill(password)
  await autoId(page, 'LoginView-submit').tap()
}

test.describe('workshop password reset on a phone', () => {
  // 401s are the signed-out session probes and the refused old password; the
  // 400 is the used link being refused. All are the point of the test. One
  // pattern, not two: a two-element array whose second entry is a RegExp is
  // parsed by Playwright as a [value, options] tuple.
  test.use({ expectedConsoleErrors: [/the server responded with a status of (400|401)/] })

  // Asked once, before any email is sent, so a missing key file, grant or
  // mailbox owner is named with its fix instead of a test polling an inbox
  // for ninety seconds. Here and not in the suite's preflight: only this
  // spec reads mail, so only a run that includes it depends on the mailbox.
  test.beforeAll(() => {
    const { username } = e2eCredentials('workshop')
    try {
      latestResetLink(username, new Date().toISOString())
    } catch (error) {
      throw new Error(
        `The reset mailbox ${mailboxOwner()} could not be read. Check GCP_CREDENTIALS, that the ` +
          "Workspace's domain-wide delegation grants " +
          'https://www.googleapis.com/auth/gmail.readonly, and that E2E_RESET_MAILBOX_OWNER is a ' +
          'user in that Workspace whose mailbox receives E2E_WORKSHOP_USERNAME.',
        { cause: error },
      )
    }
  })

  // The reset changes the workshop login's password, and every later phone
  // test signs in with the configured one. The fixtures command re-sets it.
  test.afterEach(() => {
    runManagePy(['e2e_ensure_fixtures'])
  })

  test('resets a forgotten password from the emailed link and signs in with it', async ({
    page,
    baseURL,
  }, testInfo) => {
    const { username, password: oldPassword } = e2eCredentials('workshop')
    const requestedAt = new Date().toISOString()

    await test.step('asks for a reset from the login screen', async () => {
      await page.goto('/login')
      await autoId(page, 'login-forgot-password').tap()
      await expect(page).toHaveURL(/\/forgot-password/)
      expect(await fontSizePx(page, 'ForgotPasswordPage-email')).toBeGreaterThanOrEqual(
        IOS_NO_ZOOM_FONT_PX,
      )
      await autoId(page, 'ForgotPasswordPage-email').fill(username)
      await autoId(page, 'ForgotPasswordPage-submit').tap()
      await expect(autoId(page, 'ForgotPasswordPage-sent')).toBeVisible()
      await testInfo.attach('forgot-password-sent', {
        body: await page.screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
      })
    })

    let link = ''
    await test.step('the email arrives with a link to this app over https', async () => {
      // Mail delivery is Google's clock, not the app's: the worker sends, the
      // message crosses Gmail, and only then can it be read. Polled, because
      // nothing in the page changes when it lands.
      await expect
        .poll(() => latestResetLink(username, requestedAt), {
          timeout: 90_000,
          intervals: [3_000],
          message: `no reset email reached ${mailboxOwner()} for ${username}`,
        })
        .not.toBeNull()
      link = z.string().parse(latestResetLink(username, requestedAt))

      const linked = new URL(link)
      expect(linked.protocol).toBe('https:')
      expect(linked.host).toBe(new URL(z.string().parse(baseURL)).host)
      expect(linked.pathname).toBe('/reset-password')
    })

    await test.step('the link opens the reset screen and takes a new password', async () => {
      await page.goto(link)
      await expect(autoId(page, 'ResetPasswordPage-new')).toBeVisible()
      expect(await fontSizePx(page, 'ResetPasswordPage-new')).toBeGreaterThanOrEqual(
        IOS_NO_ZOOM_FONT_PX,
      )
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow, 'the reset screen must not scroll sideways').toBeLessThanOrEqual(0)
      await testInfo.attach('reset-password', {
        body: await page.screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
      })

      await autoId(page, 'ResetPasswordPage-new').fill(NEW_PASSWORD)
      await autoId(page, 'ResetPasswordPage-confirm').fill(NEW_PASSWORD)
      await autoId(page, 'ResetPasswordPage-submit').tap()
      await expect(page.getByText('Password reset. Sign in with your new password.')).toBeVisible()
      await expect(page).toHaveURL(/\/login/)
    })

    await test.step('the new password signs in', async () => {
      await signIn(page, username, NEW_PASSWORD)
      await expect(page).toHaveURL(/\/kanban/)
      await expect(autoId(page, 'kanban-page')).toBeVisible()
      await autoId(page, 'AppNavbar-logout').tap()
      await expect(page).toHaveURL(/\/login/)
    })

    await test.step('the old password no longer does', async () => {
      await signIn(page, username, oldPassword)
      await expect(autoId(page, 'LoginView-error')).toBeVisible()
      await expect(page).toHaveURL(/\/login/)
    })

    await test.step('the used link is refused', async () => {
      await page.goto(link)
      await autoId(page, 'ResetPasswordPage-new').fill('Another-Password-93!')
      await autoId(page, 'ResetPasswordPage-confirm').fill('Another-Password-93!')
      await autoId(page, 'ResetPasswordPage-submit').tap()
      await expect(autoId(page, 'ResetPasswordPage-error')).toContainText('invalid or has expired')
      await expect(page).toHaveURL(/\/reset-password/)
    })
  })
})
