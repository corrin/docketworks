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
 * - The /xero screen is not yet ported to v2; the button names below
 *   ("Login with Xero" / "Start Sync" / "Disconnect") are v1's and must be
 *   kept in sync when that screen lands. Xero's own selectors (#xl-form-*)
 *   are Xero's pages, unchanged.
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

    // Navigate to the Xero integration page
    console.log('Navigating to /xero...')
    await page.goto(`${frontendUrl}/xero`)
    await page.waitForLoadState('networkidle')

    // Wait for loading to complete - one of these buttons will appear:
    // - "Login with Xero" if not connected
    // - "Start Sync" / "Disconnect" if connected
    console.log('Waiting for Xero connection status to load...')
    const loginButton = page.getByRole('button', { name: /login with xero/i })
    const startSyncButton = page.getByRole('button', { name: /start sync/i })
    const disconnectButton = page.getByRole('button', { name: /disconnect/i })

    // Wait for any of these buttons to become visible (loading complete)
    await Promise.race([
      loginButton.waitFor({ state: 'visible', timeout: 30000 }),
      startSyncButton.waitFor({ state: 'visible', timeout: 30000 }),
      disconnectButton.waitFor({ state: 'visible', timeout: 30000 }),
    ])

    // Now check which state we're in
    const isAlreadyConnected =
      (await startSyncButton.isVisible()) || (await disconnectButton.isVisible())

    if (isAlreadyConnected) {
      console.log('Already connected to Xero - no login needed')
      await browser.close()
      return
    }

    // Click Login with Xero button
    console.log('Not connected, clicking Login with Xero...')
    await loginButton.click()

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
    console.log('On consent page, clicking Continue...')

    // Click the Continue/Allow button on consent page
    const continueButton = page.getByRole('button', { name: /continue|allow|approve/i })
    await continueButton.waitFor({ timeout: 10000 })
    await continueButton.click()

    // Wait for redirect back to our app
    await page.waitForURL(`${frontendUrl}/**`, { timeout: 60000 })

    console.log('Xero login successful!')
    console.log(`Final URL: ${page.url()}`)
  } catch (error) {
    console.error('Error during Xero login:', error)
    await page.screenshot({ path: 'xero-login-error.png' })
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
