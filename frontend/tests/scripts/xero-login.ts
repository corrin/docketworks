/**
 * Xero OAuth Login Utility
 *
 * Usage:
 *   npx tsx tests/scripts/xero-login.ts
 *
 * Also exports ensureXeroConnected() for pre-run automation.
 *
 * NOT unattended: when Xero demands MFA this waits up to 120s for a human to
 * approve the push notification on their phone.
 *
 * Ported from v1 (tests/scripts/xero-login.ts). Adaptations:
 * - App login selectors use v2's data-automation-id attributes
 *   (LoginView-username/-password/-submit, src/routes/login.tsx) instead of
 *   v1's #username/#password ids.
 * - Env loading is anchored to this file (frontend/.env then .env.test
 *   override), matching playwright.config.ts, instead of cwd-relative
 *   dotenv.config() — the script behaves the same from any directory.
 * - It drives the BACKEND OAuth entry point, `GET /api/xero/authenticate/`,
 *   rather than v1's `/xero` screen. That screen has no v2 counterpart, and
 *   waiting for its "Login with Xero" button made this script unrunnable
 *   here — it could only ever time out. The backend view is the same flow
 *   with one less layer: it stashes CSRF state in the session and redirects
 *   to Xero's consent page, and it is guarded by the office-staff cookie the
 *   app login below already obtains. Xero's own selectors (#xl-form-*) are
 *   Xero's pages, unchanged.
 */

import { chromium, errors as playwrightErrors, type Browser } from '@playwright/test'
import dotenv from 'dotenv'
import fs from 'fs'
import path from 'path'
import { getBackendEnv, getFrontendDir } from './db-backup-utils'

const frontendDir = getFrontendDir()
dotenv.config({ path: path.join(frontendDir, '.env') })
const testEnvPath = path.join(frontendDir, '.env.test')
if (fs.existsSync(testEnvPath)) {
  dotenv.config({ path: testEnvPath, override: true })
}

async function launchBrowserWithFallback(): Promise<Browser> {
  try {
    return await chromium.launch({ headless: true })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    // WSL denies spawning the bundled Chromium (spawn EPERM); a system
    // browser channel works where the download does not.
    const isPermissionError = message.includes('spawn EPERM')
    const preferredChannel = process.env.PLAYWRIGHT_BROWSER_CHANNEL

    if (!isPermissionError && !preferredChannel) {
      throw error
    }

    const channelsToTry = preferredChannel ? [preferredChannel] : ['msedge', 'chrome']

    for (const channel of channelsToTry) {
      try {
        console.log(`[xero] Retrying Chromium launch with channel: ${channel}`)
        return await chromium.launch({ headless: true, channel })
      } catch (channelError) {
        const channelMessage =
          channelError instanceof Error ? channelError.message : String(channelError)
        console.warn(`[xero] Failed to launch with channel ${channel}: ${channelMessage}`)
      }
    }

    throw error
  }
}

export async function ensureXeroConnected(): Promise<void> {
  const xeroUsername = process.env.XERO_USERNAME
  const xeroPassword = process.env.XERO_PASSWORD
  const appUsername = process.env.E2E_TEST_USERNAME
  const appPassword = process.env.E2E_TEST_PASSWORD
  const backendEnv = getBackendEnv()
  const appDomain = backendEnv.APP_DOMAIN
  if (!appDomain) {
    throw new Error('APP_DOMAIN must be set in backend .env')
  }
  // The Xero app's registered OAuth redirect points at APP_DOMAIN, so the
  // consent round-trip only works against that host — never a localhost
  // preview server, which is why this ignores E2E_BASE_URL.
  const frontendUrl = `https://${appDomain}`

  if (!xeroUsername || !xeroPassword) {
    throw new Error('XERO_USERNAME and XERO_PASSWORD must be set in .env')
  }

  if (!appUsername || !appPassword) {
    throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
  }

  const browser = await launchBrowserWithFallback()
  const page = await browser.newPage()

  try {
    // First, log into the app
    console.log(`Logging into app as: ${appUsername}`)
    await page.goto(`${frontendUrl}/login`)
    await page.locator('[data-automation-id="LoginView-username"]').fill(appUsername)
    await page.locator('[data-automation-id="LoginView-password"]').fill(appPassword)
    await page.locator('[data-automation-id="LoginView-submit"]').click()
    await page.waitForURL('**/kanban')
    console.log('App login successful')

    // Ask the app, not a screen, whether the connection is live. Only a 200
    // with `connected: true` counts; anything else means connect, including a
    // 500 — the ping reports a failed refresh that way, and the most ordinary
    // one is "invalid_grant: Refresh token has been consumed", a dead token
    // whose fix is precisely the consent flow below.
    console.log('Checking the Xero connection via /api/xero/ping/...')
    const ping = await page.request.get(`${frontendUrl}/api/xero/ping/`)
    if (!ping.ok()) {
      console.log(`Xero ping returned ${ping.status()}: ${await ping.text()}`)
    } else {
      const pingBody: unknown = await ping.json()
      if (
        typeof pingBody === 'object' &&
        pingBody !== null &&
        (pingBody as { connected?: unknown }).connected === true
      ) {
        console.log('Already connected to Xero - no login needed')
        await browser.close()
        return
      }
    }

    // The backend entry point: it stashes CSRF state in the session and
    // redirects to Xero's consent page. Same browser context, so the
    // office-staff cookie from the app login above authorises it.
    console.log('Not connected, starting the OAuth flow...')
    await page.goto(`${frontendUrl}/api/xero/authenticate/`)

    // Wait for Xero login form
    await page.waitForSelector('#xl-form-email', { timeout: 30000 })
    console.log(`Logging into Xero as: ${xeroUsername}`)

    // Fill credentials and submit
    await page.locator('#xl-form-email').fill(xeroUsername)
    await page.locator('#xl-form-password').fill(xeroPassword)
    await page.locator('#xl-form-submit').click()

    // Detect MFA prompt by waiting for either the MFA text or the consent
    // URL — whichever appears first. `isVisible({ timeout })` is a no-op
    // (the option is deprecated and returns immediately), so a polling
    // race is the reliable check.
    const mfaPrompt = page
      .getByText("We've sent a notification to your phone")
      .waitFor({ timeout: 30000 })
      .then(() => 'mfa' as const)
    const consentNav = page
      .waitForURL(/^https:\/\/(?:[\w-]+\.)?xero\.com\//, { timeout: 30000 })
      .then(() => 'consent' as const)
    // Only treat Playwright TimeoutError as the 'timeout' outcome; let
    // page crashes, navigation failures, and other errors propagate so
    // the real failure mode shows up in CI logs instead of a generic
    // "neither appeared" message.
    const outcome = await Promise.race([mfaPrompt, consentNav]).catch((err) => {
      if (err instanceof playwrightErrors.TimeoutError) return 'timeout' as const
      throw err
    })
    if (outcome === 'mfa') {
      console.log('MFA required - please approve on your phone...')
      await page.waitForURL(/^https:\/\/(?:[\w-]+\.)?xero\.com\//, { timeout: 120000 })
    } else if (outcome === 'timeout') {
      throw new Error(
        'Neither MFA prompt nor consent page appeared within 30s after Xero login submit',
      )
    }
    // Consent is not guaranteed to be asked for. After MFA, Xero runs a chain
    // of identity redirects (login.xero.com -> authorize.xero.com/signin-oidc)
    // and then EITHER renders the authorise page OR, when this org has already
    // been authorised, drops straight back on our redirect URI. So race the
    // two, the same way the MFA prompt is raced above.
    //
    // v1 waited 10s for the button unconditionally and inherited both bugs:
    // the redirect chain alone outlasts that window, and an org that needs no
    // consent never shows a button to wait for.
    const continueButton = page.getByRole('button', { name: /continue|allow|approve/i })
    const consentShown = continueButton.waitFor({ timeout: 90000 }).then(() => 'consent' as const)
    const backAtApp = page
      .waitForURL(`${frontendUrl}/**`, { timeout: 90000 })
      .then(() => 'returned' as const)
    const step = await Promise.race([consentShown, backAtApp]).catch((err) => {
      if (err instanceof playwrightErrors.TimeoutError) return 'timeout' as const
      throw err
    })

    if (step === 'timeout') {
      throw new Error(
        `Stalled after Xero login: no authorise button and no return to ${frontendUrl} ` +
          `within 90s. Last URL: ${page.url()}`,
      )
    }
    if (step === 'consent') {
      console.log('On consent page, clicking Continue...')
      await continueButton.click()
      await page.waitForURL(`${frontendUrl}/**`, { timeout: 60000 })
    } else {
      console.log('Xero had already authorised this organisation; no consent needed.')
    }

    console.log('Xero login successful!')
    console.log(`Final URL: ${page.url()}`)
  } catch (error) {
    console.error('Error during Xero login:', error)
    // Anchored, not relative: a bare filename resolves against the process
    // CWD, which put this in the frontend package root — outside every
    // gitignored artifact directory, so it turned up staged for commit with a
    // Xero login page captured in it. test-results/ is where the rest of the
    // run's artifacts go and run_e2e.sh wipes it, so it cannot accumulate.
    const artifactDir = path.join(frontendDir, 'test-results')
    fs.mkdirSync(artifactDir, { recursive: true })
    await page.screenshot({ path: path.join(artifactDir, 'xero-login-error.png') })
    throw error
  } finally {
    await browser.close()
  }
}

// Run directly if called as a script
const isMainModule = import.meta.url === `file://${process.argv[1]}`
if (isMainModule) {
  ensureXeroConnected().catch((error) => {
    console.error(error)
    process.exit(1)
  })
}
