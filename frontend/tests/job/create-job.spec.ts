import { test, expect } from '../fixtures/auth'
import {
  autoId,
  dismissToasts,
  expectStepUnder,
  submitJobAndWaitForCreatedJob,
  TEST_COMPANY_NAME,
  waitForSettingsInitialized,
} from '../fixtures/helpers'

/**
 * Sequential test cases for job creation.
 * These tests MUST run in order as each builds on the previous state:
 * - Test 1: Company has 0 people → creates first person (becomes primary)
 * - Test 2: Company has 1 person → creates second person
 * - Test 3: Company has 2 people → selects non-primary person
 */
const jobTestCases = [
  {
    name: 'T&M with first person',
    pricingValue: 'time_materials',
    ballparkMaterials: '500',
    ballparkHours: '4',
    createPerson: true,
    personToCreate: { name: '[TEST] Person', email: 'test@example.com' },
    expectedTab: 'estimate',
  },
  {
    name: 'Fixed Price with second person',
    pricingValue: 'fixed_price',
    ballparkMaterials: '1000',
    ballparkHours: '8',
    createPerson: true,
    personToCreate: { name: '[TEST] Another Person', email: 'another@example.com' },
    expectedTab: 'quote',
  },
  {
    name: 'Fixed Price selecting non-primary person',
    pricingValue: 'fixed_price',
    ballparkMaterials: '750',
    ballparkHours: '6',
    createPerson: false,
    personToSelect: '[TEST] Another Person', // Select the non-primary person
    expectedTab: 'quote',
  },
] as const

const CREATE_JOB_BUDGET_MS = {
  navigateToCreatePage: 2500,
  searchAndSelectCompany: 1500,
  personSelection: 2500,
  submitAndRedirect: 3500,
  defaultPayItemCreateJob: 4500,
  defaultPayItemSettingsLoad: 2500,
} as const

// Use describe.serial to ensure tests run in order (they depend on each other)
test.describe.serial('create job', () => {
  for (const tc of jobTestCases) {
    test(`create ${tc.name} job with company and person`, async ({ authenticatedPage: page }) => {
      // Generate unique job name to avoid conflicts
      const timestamp = Date.now()
      const jobName = `[TEST] Job ${tc.name} ${timestamp}`

      await expectStepUnder(
        'navigate to create job page',
        CREATE_JOB_BUDGET_MS.navigateToCreatePage,
        async () => {
          await autoId(page, 'AppNavbar-create-job').click()
          await page.waitForURL('**/jobs/create')
          await expect(autoId(page, 'JobCreateView-title')).toContainText('Create New Job')
        },
      )

      await expectStepUnder(
        'search and select company',
        CREATE_JOB_BUDGET_MS.searchAndSelectCompany,
        async () => {
          console.log('Searching for company ABC...')
          const companyInput = autoId(page, 'CompanyLookup-input')
          await companyInput.fill('ABC')

          // Wait for results dropdown
          await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })

          // Click on the test company using role
          console.log(`Selecting ${TEST_COMPANY_NAME}...`)
          await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()

          // Verify selection
          await expect(companyInput).toHaveValue(TEST_COMPANY_NAME)
        },
      )

      await test.step('enter job name', async () => {
        await autoId(page, 'JobCreateView-name-input').fill(jobName)
      })

      await expectStepUnder(
        'select or create person',
        CREATE_JOB_BUDGET_MS.personSelection,
        async () => {
          // Click the button to open person modal
          console.log('Opening person modal...')
          await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })

          // Wait for modal
          console.log('Waiting for modal...')
          await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

          if (tc.createPerson && tc.personToCreate) {
            console.log(`Creating new person: ${tc.personToCreate.name}`)

            // Debug: capture button state
            const submitButton = autoId(page, 'PersonSelectionModal-submit')
            const buttonText = await submitButton.textContent()
            const buttonDisabled = await submitButton.isDisabled()
            console.log(`Button text: "${buttonText}", disabled: ${buttonDisabled}`)

            // Wait for form to be ready - button should show "Create Person" not "Saving..."
            try {
              await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })
            } catch (e) {
              // Capture state on failure
              const finalText = await submitButton.textContent()
              console.log(`TIMEOUT - button still shows: "${finalText}"`)
              await page.screenshot({ path: `test-results/debug-button-${Date.now()}.png` })
              throw e
            }

            // Fill the Create New Person form
            await autoId(page, 'PersonSelectionModal-name-input').fill(tc.personToCreate.name)
            await autoId(page, 'PersonSelectionModal-email-input').fill(tc.personToCreate.email)

            // Click Create Person
            await submitButton.click()
          } else if (tc.personToSelect) {
            console.log(`Selecting existing person: ${tc.personToSelect}`)
            // Wait for people list
            await autoId(page, 'PersonSelectionModal-select-button')
              .first()
              .waitFor({ timeout: 10000 })

            // Find the person card by name and click its Select button
            const personCard = page
              .locator(`[data-automation-id^="PersonSelectionModal-card-"]`)
              .filter({
                hasText: tc.personToSelect,
              })
            await personCard.hover()
            await personCard
              .locator('[data-automation-id="PersonSelectionModal-select-button"]')
              .click()
          }

          // Wait for modal to close
          console.log('Waiting for modal to close...')
          await autoId(page, 'PersonSelectionModal-container').waitFor({
            state: 'hidden',
            timeout: 10000,
          })
        },
      )

      await test.step('set ballpark estimates', async () => {
        await autoId(page, 'JobCreateView-estimated-materials').fill(tc.ballparkMaterials)
        await autoId(page, 'JobCreateView-estimated-time').fill(tc.ballparkHours)
      })

      await test.step('select pricing method', async () => {
        await autoId(page, 'JobCreateView-pricing-method').selectOption(tc.pricingValue)
      })

      await expectStepUnder(
        'submit and verify job created',
        CREATE_JOB_BUDGET_MS.submitAndRedirect,
        async () => {
          const startTime = Date.now()
          console.log(`[${new Date().toISOString()}] Submitting job...`)

          // Dismiss any toast notifications that might block the button
          await dismissToasts(page)

          const url = await submitJobAndWaitForCreatedJob(page, tc.expectedTab)
          console.log(
            `[${new Date().toISOString()}] Clicked Create Job button (${Date.now() - startTime}ms)`,
          )
          console.log(
            `[${new Date().toISOString()}] Redirected (${Date.now() - startTime}ms total)`,
          )

          expect(url).toContain('/jobs/')
          expect(url).toContain(`tab=${tc.expectedTab}`)

          console.log(
            `[${new Date().toISOString()}] Successfully created ${tc.name} job: ${jobName} (${Date.now() - startTime}ms total)`,
          )
        },
      )
    })
  }
})

test.describe('new job default pay item', () => {
  test('newly created job defaults to Ordinary time pay item', async ({
    authenticatedPage: page,
  }) => {
    const timestamp = Date.now()
    const jobName = `[TEST] Pay Item Job ${timestamp}`

    await expectStepUnder(
      'create a new job',
      CREATE_JOB_BUDGET_MS.defaultPayItemCreateJob,
      async () => {
        await autoId(page, 'AppNavbar-create-job').click()
        await page.waitForURL('**/jobs/create')

        // Select company
        const companyInput = autoId(page, 'CompanyLookup-input')
        await companyInput.fill('ABC')
        await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
        await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()

        // Enter job name
        await autoId(page, 'JobCreateView-name-input').fill(jobName)

        // Select person - open modal and create or select one
        await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
        await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

        // Check if there are existing persons to select
        const selectButtons = autoId(page, 'PersonSelectionModal-select-button')
        const hasExistingPeople = (await selectButtons.count()) > 0

        if (hasExistingPeople) {
          // Select the first existing person
          await selectButtons.first().click()
        } else {
          // Create a new person
          const submitButton = autoId(page, 'PersonSelectionModal-submit')
          await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })
          await autoId(page, 'PersonSelectionModal-name-input').fill(`[TEST] Person ${timestamp}`)
          await autoId(page, 'PersonSelectionModal-email-input').fill(
            `test${timestamp}@example.com`,
          )
          await submitButton.click()
        }

        await autoId(page, 'PersonSelectionModal-container').waitFor({
          state: 'hidden',
          timeout: 10000,
        })

        // Set ballpark estimates
        await autoId(page, 'JobCreateView-estimated-materials').fill('100')
        await autoId(page, 'JobCreateView-estimated-time').fill('2')

        // Submit
        await dismissToasts(page)
        await submitJobAndWaitForCreatedJob(page, 'estimate')
      },
    )

    await expectStepUnder(
      'navigate to job settings and verify default pay item',
      CREATE_JOB_BUDGET_MS.defaultPayItemSettingsLoad,
      async () => {
        // Navigate to Job Settings tab
        await autoId(page, 'JobViewTabs-jobSettings').click()
        await autoId(page, 'JobSettingsTab-default-pay-item').waitFor({ timeout: 10000 })
        await waitForSettingsInitialized(page)

        // Verify the default pay item is "Ordinary time"
        const payItemSelect = autoId(page, 'JobSettingsTab-default-pay-item')

        // Get the selected option text
        const selectedOption = payItemSelect.locator('option:checked')
        const selectedText = await selectedOption.textContent()

        console.log(`Default pay item for new job: "${selectedText}"`)

        // Verify it's "Ordinary Time" (the expected default)
        expect(selectedText).toBe('Ordinary Time')
      },
    )
  })
})
