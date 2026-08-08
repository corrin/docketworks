import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'
import fs from 'node:fs'
import path from 'node:path'

// Load environment variables from .env, then override with .env.test when
// present (same pattern as v1). Provides E2E_TEST_USERNAME / E2E_TEST_PASSWORD
// and optionally E2E_BASE_URL.
dotenv.config()
const testEnvPath = path.resolve(process.cwd(), '.env.test')
if (fs.existsSync(testEnvPath)) {
  dotenv.config({ path: testEnvPath, override: true })
}

// Env-driven baseURL; defaults to the local production-build preview server
// (npm run preview:e2e — vite preview proxies /api to the backend on :8000).
// The one-shot local-stack runner wins over a developer's optional
// E2E_BASE_URL so it can never start local services and test another host.
const externalBaseURL = process.env.E2E_MANAGED_BASE_URL ?? process.env.E2E_BASE_URL
const baseURL = externalBaseURL ?? 'http://localhost:4173'

export default defineConfig({
  globalSetup: './tests/scripts/global-setup.ts',
  globalTeardown: './tests/scripts/global-teardown.ts',
  testDir: './tests/e2e',
  fullyParallel: false, // Run tests sequentially to avoid database conflicts
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Single worker to avoid parallel database conflicts
  maxFailures: 1, // Stop early — don't wait if something's broken
  reporter: [
    ['html', { open: 'never' }], // Don't auto-open report (blocks process)
    ['list', { printSteps: true }], // Show steps and console output
  ],

  use: {
    baseURL,
    trace: 'on',
    screenshot: 'only-on-failure',
    // 0 = no per-action cap; the test-level timeout below is the only hard
    // limit (v1 rationale: an action that still fails after the full budget
    // cannot merely have been slow).
    actionTimeout: 0,
    navigationTimeout: 0,
  },

  // The single hard timeout. Generous so that reaching it is evidence the page
  // is broken rather than slow.
  timeout: 120000,

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  outputDir: 'test-results/',

  // E2E always runs against the production build (v1's preview:e2e script).
  // When E2E_BASE_URL points at an externally managed server, skip the local one.
  ...(externalBaseURL
    ? {}
    : {
        webServer: {
          command: 'npm run preview:e2e',
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120000,
        },
      }),
})
