import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'
import fs from 'fs'
import path from 'path'

// Load environment variables from .env, then override with .env.test when present.
dotenv.config()
const testEnvPath = path.resolve(process.cwd(), '.env.test')
if (fs.existsSync(testEnvPath)) {
  dotenv.config({ path: testEnvPath, override: true })
}

export default defineConfig({
  globalSetup: './tests/scripts/global-setup.ts',
  globalTeardown: './tests/scripts/global-teardown.ts',
  testDir: './tests',
  fullyParallel: false, // Run tests sequentially to avoid database conflicts
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Single worker to avoid parallel database conflicts
  reporter: [
    ['html', { open: 'never' }], // Don't auto-open report (blocks process)
    ['list', { printSteps: true }], // Show steps and console output
  ],

  use: {
    baseURL: process.env.VITE_FRONTEND_BASE_URL || 'http://localhost:5173',
    trace: 'on', // Always capture traces for timing analysis
    screenshot: 'only-on-failure',
    actionTimeout: 30000,
    navigationTimeout: 60000,
  },

  // Increase test timeout to 60 seconds for operations that involve backend API calls
  timeout: 60000,

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Output test artifacts (videos, traces) to test-results/
  outputDir: 'test-results/',
})
