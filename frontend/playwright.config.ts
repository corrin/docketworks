import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'
import fs from 'fs'
import path from 'path'
import { getBackendEnv } from './tests/scripts/db-backup-utils'

// Load environment variables from .env, then override with .env.test when present.
dotenv.config()
const testEnvPath = path.resolve(process.cwd(), '.env.test')
if (fs.existsSync(testEnvPath)) {
  dotenv.config({ path: testEnvPath, override: true })
}

const backendEnv = getBackendEnv()
const appDomain = backendEnv.APP_DOMAIN
if (!appDomain) {
  throw new Error('APP_DOMAIN must be set in backend .env')
}
const baseURL = `https://${appDomain}`

export default defineConfig({
  globalSetup: './tests/scripts/global-setup.ts',
  globalTeardown: './tests/scripts/global-teardown.ts',
  testDir: './tests',
  fullyParallel: false, // Run tests sequentially to avoid database conflicts
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Single worker to avoid parallel database conflicts
  maxFailures: 1, // Stop early — full suite is slow, don't wait if something's broken
  reporter: [
    ['html', { open: 'never' }], // Don't auto-open report (blocks process)
    ['list', { printSteps: true }], // Show steps and console output
    // Custom reporter — appends per-test wall durations of passing tests
    // to test-history/ so we can reason about timeouts from real history.
    // Must run as a reporter (not in globalTeardown) because reporter onEnd
    // fires after all results are collected, while globalTeardown runs
    // earlier in Playwright's lifecycle.
    ['./tests/scripts/history-reporter.ts'],
  ],

  use: {
    baseURL,
    trace: 'on', // Always capture traces for timing analysis
    screenshot: 'only-on-failure',
    // 0 = no per-action cap; the test-level timeout below is the only hard
    // limit, matching what expectStepUnder already documents. A per-action cap
    // throws away the diagnosis: a click that dies at 30s might merely have
    // been slow, but one that still fails after the full 120s cannot be — so
    // capping early leaves "it was just slow" permanently unfalsifiable.
    actionTimeout: 0,
    navigationTimeout: 0,
  },

  // The single hard timeout. Generous so that reaching it is evidence the page
  // is broken rather than slow, not a false positive on slow hardware.
  timeout: 120000,

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Output test artifacts (videos, traces) to test-results/
  outputDir: 'test-results/',
})
