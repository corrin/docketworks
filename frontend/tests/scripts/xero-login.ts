/**
 * Xero OAuth Login Utility
 *
 * Usage:
 *   npx ts-node tests/scripts/xero-login.ts
 *
 * Also exports ensureXeroConnected() for use in global-setup.ts
 */

import { chromium, type Browser } from '@playwright/test'
import dotenv from 'dotenv'

dotenv.config()

async function launchBrowserWithFallback(): Promise<Browser> {
  try {
    return await chromium.launch({ headless: true })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
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
  const frontendUrl = process.env.VITE_FRONTEND_BASE_URL

  if (!xeroUsername || !xeroPassword) {
    throw new Error('XERO_USERNAME and XERO_PASSWORD must be set in .env')
  }

  if (!appUsername || !appPassword) {
    throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
  }

  if (!frontendUrl) {
    throw new Error('VITE_FRONTEND_BASE_URL must be set in .env')
  }

  const browser = await launchBrowserWithFallback()
  const page = await browser.newPage()

  try {
    // First, log into the app
    console.log(`Logging into app as: ${appUsername}`)
    await page.goto(`${frontendUrl}/login`)
    await page.locator('#username').fill(appUsername)
    await page.locator('#password').fill(appPassword)
    await page.getByRole('button', { name: 'Sign In' }).click()
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

    // Check if MFA is required (phone notification)
    const mfaPage = page.getByText("We've sent a notification to your phone")
    const isMfaRequired = await mfaPage.isVisible({ timeout: 5000 }).catch(() => false)

    if (isMfaRequired) {
      console.log('MFA required - please approve on your phone...')
      // Wait up to 2 minutes for user to approve MFA
      await page.waitForURL(/authorize\.xero\.com/, { timeout: 120000 })
    } else {
      // Wait for consent page to load (authorize.xero.com)
      await page.waitForURL(/authorize\.xero\.com/, { timeout: 30000 })
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
