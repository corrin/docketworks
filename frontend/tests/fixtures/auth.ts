import { test as base, expect, type Page } from '@playwright/test'
import {
  dismissToasts,
  autoId,
  enableNetworkLogging,
  expectStepUnder,
  submitJobAndWaitForCreatedJob,
  TEST_CLIENT_NAME,
} from './helpers'

// Define fixture types
type AuthFixtures = {
  authenticatedPage: Page
}

type WorkerFixtures = {
  // Worker-scoped fixtures for shared test data
  sharedEditJobUrl: string
}

const SHARED_EDIT_JOB_BUDGET_MS = {
  navigateToCreatePage: 2500,
  searchAndSelectClient: 1500,
  fillJobDetails: 1000,
  contactSelection: 2500,
  submitAndRedirect: 3500,
} as const

export const test = base.extend<AuthFixtures, WorkerFixtures>({
  authenticatedPage: async ({ page }, use, testInfo) => {
    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD

    if (!username || !password) {
      throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
    }

    // Enable network logging for all tests
    enableNetworkLogging(page, testInfo.title)

    await base.step('authenticatedPage: login', async () => {
      // Navigate to login page
      await page.goto('/login')

      // Fill login form
      await page.locator('#username').fill(username)
      await page.locator('#password').fill(password)

      // Click sign in button
      await page.getByRole('button', { name: 'Sign In' }).click()

      // Wait for redirect to kanban (default landing page after login)
      await page.waitForURL('**/kanban')
    })

    // Enable debug logging if DEBUG env var is set
    if (process.env.DEBUG === 'true') {
      await page.evaluate(() => localStorage.setItem('debug', 'true'))
    }

    // Pass the authenticated page to the test
    await use(page)
  },

  // Worker-scoped fixture that creates a job once per worker
  // This allows running individual tests that depend on a shared job
  sharedEditJobUrl: [
    async ({ browser }, use) => {
      const username = process.env.E2E_TEST_USERNAME
      const password = process.env.E2E_TEST_PASSWORD

      if (!username || !password) {
        throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
      }

      // Create a new context and page for job creation
      const context = await browser.newContext()
      const page = await context.newPage()

      await base.step('sharedEditJobUrl: login', async () => {
        await page.goto('/login')
        await page.locator('#username').fill(username)
        await page.locator('#password').fill(password)
        await page.getByRole('button', { name: 'Sign In' }).click()
        await page.waitForURL('**/kanban')
      })

      // Create the job using the helper (but with fixed_price for edit tests)
      const timestamp = Date.now()
      const jobName = `[TEST] Edit Job ${timestamp}`

      await expectStepUnder(
        'sharedEditJobUrl: navigate to create job page',
        SHARED_EDIT_JOB_BUDGET_MS.navigateToCreatePage,
        async () => {
          await autoId(page, 'AppNavbar-create-job').click()
          await page.waitForURL('**/jobs/create')
          await page.waitForLoadState('networkidle')
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: search and select client',
        SHARED_EDIT_JOB_BUDGET_MS.searchAndSelectClient,
        async () => {
          const clientInput = autoId(page, 'ClientLookup-input')
          await clientInput.waitFor({ timeout: 10000 })
          await clientInput.fill('ABC')
          await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
          await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: fill job details',
        SHARED_EDIT_JOB_BUDGET_MS.fillJobDetails,
        async () => {
          await autoId(page, 'JobCreateView-name-input').fill(jobName)
          await autoId(page, 'JobCreateView-estimated-materials').fill('1000')
          await autoId(page, 'JobCreateView-estimated-time').fill('8')
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: select or create contact',
        SHARED_EDIT_JOB_BUDGET_MS.contactSelection,
        async () => {
          await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })
          await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })

          const selectButtons = autoId(page, 'ContactSelectionModal-select-button')
          const selectButtonCount = await selectButtons.count()

          if (selectButtonCount > 0) {
            await selectButtons.first().click()
          } else {
            const submitButton = autoId(page, 'ContactSelectionModal-submit')
            await autoId(page, 'ContactSelectionModal-name-input').fill(
              `[TEST] Contact ${timestamp}`,
            )
            await autoId(page, 'ContactSelectionModal-email-input').fill(
              `test${timestamp}@example.com`,
            )
            await submitButton.click()
          }

          await autoId(page, 'ContactSelectionModal-container').waitFor({
            state: 'hidden',
            timeout: 10000,
          })
        },
      )

      await expectStepUnder(
        'sharedEditJobUrl: submit fixed price job',
        SHARED_EDIT_JOB_BUDGET_MS.submitAndRedirect,
        async () => {
          await autoId(page, 'JobCreateView-pricing-method').selectOption('fixed_price')
          await dismissToasts(page)
          await submitJobAndWaitForCreatedJob(page, 'quote')
        },
      )

      const jobUrl = page.url()
      console.log(`[Fixture] Created shared edit job at: ${jobUrl}`)

      await context.close()

      // Provide the URL to tests
      await use(jobUrl)
    },
    { scope: 'worker' }, // Share across all tests in the worker
  ],
})

export { expect }
