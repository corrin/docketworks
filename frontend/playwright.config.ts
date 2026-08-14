import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'
import fs from 'node:fs'
import path from 'node:path'

// Anchored to this file's own directory, not process.cwd(): npm --prefix and
// direct `npx playwright test` invocations from the repo root both leave cwd
// outside frontend/, and a cwd-relative path would then silently miss
// .env.test (dropping E2E_TEST_USERNAME/PASSWORD with no error) or scatter
// testDir/outputDir at the wrong location instead of erroring loudly.
const configDir = import.meta.dirname

// Load environment variables from .env, then override with .env.test when
// present (same pattern as v1). Provides E2E_TEST_USERNAME / E2E_TEST_PASSWORD
// and optionally E2E_BASE_URL.
dotenv.config({ path: path.join(configDir, '.env') })
const testEnvPath = path.join(configDir, '.env.test')
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
  globalSetup: path.join(configDir, 'tests/scripts/global-setup.ts'),
  globalTeardown: path.join(configDir, 'tests/scripts/global-teardown.ts'),
  testDir: path.join(configDir, 'tests/e2e'),
  fullyParallel: false, // Run tests sequentially to avoid database conflicts
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Single worker to avoid parallel database conflicts
  maxFailures: 1, // Stop early — don't wait if something's broken
  reporter: [
    ['html', { open: 'never', outputFolder: path.join(configDir, 'playwright-report') }],
    ['list', { printSteps: true }], // Show steps and console output
    // Appends per-test wall durations of completed tests to test-history/ so
    // timeouts can be reasoned about from real history. Must run as a
    // reporter (not in globalTeardown) because reporter onEnd fires after all
    // results are collected, while globalTeardown runs earlier in
    // Playwright's lifecycle.
    [path.join(configDir, 'tests/scripts/history-reporter.ts')],
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

  outputDir: path.join(configDir, 'test-results'),

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
