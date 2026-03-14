import { test, expect } from '../fixtures/auth'
import {
  autoId,
  dismissToasts,
  TEST_CLIENT_NAME,
  waitForSettingsInitialized,
} from '../fixtures/helpers'

/**
 * Sequential test cases for job creation.
 * These tests MUST run in order as each builds on the previous state:
 * - Test 1: Client has 0 contacts → creates first contact (becomes primary)
 * - Test 2: Client has 1 contact → creates second contact
 * - Test 3: Client has 2 contacts → selects non-primary contact
 */
const jobTestCases = [
  {
    name: 'T&M with first contact',
    pricingValue: 'time_materials',
    ballparkMaterials: '500',
    ballparkHours: '4',
    createContact: true,
    contactToCreate: { name: 'Test Contact Person', email: 'test@example.com' },
    expectedTab: 'estimate',
  },
  {
    name: 'Fixed Price with second contact',
    pricingValue: 'fixed_price',
    ballparkMaterials: '1000',
    ballparkHours: '8',
    createContact: true,
    contactToCreate: { name: 'Another Contact', email: 'another@example.com' },
    expectedTab: 'quote',
  },
  {
    name: 'Fixed Price selecting non-primary contact',
    pricingValue: 'fixed_price',
    ballparkMaterials: '750',
    ballparkHours: '6',
    createContact: false,
    contactToSelect: 'Another Contact', // Select the non-primary contact
    expectedTab: 'quote',
  },
]

// Use describe.serial to ensure tests run in order (they depend on each other)
test.describe.serial('create job', () => {
  for (const tc of jobTestCases) {
    test(`create ${tc.name} job with client and contact`, async ({ authenticatedPage: page }) => {
      // Generate unique job name to avoid conflicts
      const timestamp = Date.now()
      const jobName = `Test Job ${tc.name} ${timestamp}`

      await test.step('navigate to create job page', async () => {
        await autoId(page, 'AppNavbar-create-job').click()
        await page.waitForURL('**/jobs/create')
        await expect(autoId(page, 'JobCreateView-title')).toContainText('Create New Job')
      })

      await test.step('search and select client', async () => {
        console.log('Searching for client ABC...')
        const clientInput = autoId(page, 'ClientLookup-input')
        await clientInput.fill('ABC')

        // Wait for results dropdown
        await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })

        // Click on the test client using role
        console.log(`Selecting ${TEST_CLIENT_NAME}...`)
        await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()

        // Verify selection
        await expect(clientInput).toHaveValue(TEST_CLIENT_NAME)
      })

      await test.step('enter job name', async () => {
        await autoId(page, 'JobCreateView-name-input').fill(jobName)
      })

      await test.step('select or create contact person', async () => {
        // Click the button to open contact modal
        console.log('Opening contact modal...')
        await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })

        // Wait for modal
        console.log('Waiting for modal...')
        await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })

        if (tc.createContact && tc.contactToCreate) {
          console.log(`Creating new contact: ${tc.contactToCreate.name}`)

          // Debug: capture button state
          const submitButton = autoId(page, 'ContactSelectionModal-submit')
          const buttonText = await submitButton.textContent()
          const buttonDisabled = await submitButton.isDisabled()
          console.log(`Button text: "${buttonText}", disabled: ${buttonDisabled}`)

          // Wait for form to be ready - button should show "Create Contact" not "Saving..."
          try {
            await expect(submitButton).toHaveText('Create Contact', { timeout: 10000 })
          } catch (e) {
            // Capture state on failure
            const finalText = await submitButton.textContent()
            console.log(`TIMEOUT - button still shows: "${finalText}"`)
            await page.screenshot({ path: `test-results/debug-button-${Date.now()}.png` })
            throw e
          }

          // Fill the Create New Contact form
          await autoId(page, 'ContactSelectionModal-name-input').fill(tc.contactToCreate.name)
          await autoId(page, 'ContactSelectionModal-email-input').fill(tc.contactToCreate.email)

          // Click Create Contact
          await submitButton.click()
        } else if (tc.contactToSelect) {
          console.log(`Selecting existing contact: ${tc.contactToSelect}`)
          // Wait for contacts list
          await autoId(page, 'ContactSelectionModal-select-button')
            .first()
            .waitFor({ timeout: 10000 })

          // Find the contact card by name and click its Select button
          const contactCard = page
            .locator(`[data-automation-id^="ContactSelectionModal-card-"]`)
            .filter({
              hasText: tc.contactToSelect,
            })
          await contactCard.hover()
          await contactCard
            .locator('[data-automation-id="ContactSelectionModal-select-button"]')
            .click()
        }

        // Wait for modal to close
        console.log('Waiting for modal to close...')
        await autoId(page, 'ContactSelectionModal-container').waitFor({
          state: 'hidden',
          timeout: 10000,
        })
      })

      await test.step('set ballpark estimates', async () => {
        await autoId(page, 'JobCreateView-estimated-materials').fill(tc.ballparkMaterials)
        await autoId(page, 'JobCreateView-estimated-time').fill(tc.ballparkHours)
      })

      await test.step('select pricing method', async () => {
        await autoId(page, 'JobCreateView-pricing-method').selectOption(tc.pricingValue)
      })

      await test.step('submit and verify job created', async () => {
        const startTime = Date.now()
        console.log(`[${new Date().toISOString()}] Submitting job...`)

        // Dismiss any toast notifications that might block the button
        await dismissToasts(page)

        await autoId(page, 'JobCreateView-submit').click({ force: true })
        console.log(
          `[${new Date().toISOString()}] Clicked Create Job button (${Date.now() - startTime}ms)`,
        )

        // Should redirect to job edit view
        console.log(
          `[${new Date().toISOString()}] Waiting for redirect to job page with tab=${tc.expectedTab}...`,
        )
        await page.waitForURL(`**/jobs/*?*tab=${tc.expectedTab}*`, { timeout: 10000 })
        console.log(`[${new Date().toISOString()}] Redirected (${Date.now() - startTime}ms total)`)

        const url = page.url()
        expect(url).toContain('/jobs/')
        expect(url).toContain(`tab=${tc.expectedTab}`)

        console.log(
          `[${new Date().toISOString()}] Successfully created ${tc.name} job: ${jobName} (${Date.now() - startTime}ms total)`,
        )
      })
    })
  }
})

test.describe('new job default pay item', () => {
  test('newly created job defaults to Ordinary time pay item', async ({
    authenticatedPage: page,
  }) => {
    const timestamp = Date.now()
    const jobName = `Default Pay Item Test ${timestamp}`

    await test.step('create a new job', async () => {
      await autoId(page, 'AppNavbar-create-job').click()
      await page.waitForURL('**/jobs/create')

      // Select client
      const clientInput = autoId(page, 'ClientLookup-input')
      await clientInput.fill('ABC')
      await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
      await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()

      // Enter job name
      await autoId(page, 'JobCreateView-name-input').fill(jobName)

      // Select contact - open modal and create or select one
      await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })
      await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })

      // Check if there are existing contacts to select
      const selectButtons = autoId(page, 'ContactSelectionModal-select-button')
      const hasExistingContacts = (await selectButtons.count()) > 0

      if (hasExistingContacts) {
        // Select the first existing contact
        await selectButtons.first().click()
      } else {
        // Create a new contact
        const submitButton = autoId(page, 'ContactSelectionModal-submit')
        await expect(submitButton).toHaveText('Create Contact', { timeout: 10000 })
        await autoId(page, 'ContactSelectionModal-name-input').fill(`Test Contact ${timestamp}`)
        await autoId(page, 'ContactSelectionModal-email-input').fill(`test${timestamp}@example.com`)
        await submitButton.click()
      }

      await autoId(page, 'ContactSelectionModal-container').waitFor({
        state: 'hidden',
        timeout: 10000,
      })

      // Set ballpark estimates
      await autoId(page, 'JobCreateView-estimated-materials').fill('100')
      await autoId(page, 'JobCreateView-estimated-time').fill('2')

      // Submit
      await dismissToasts(page)
      await autoId(page, 'JobCreateView-submit').click({ force: true })

      // Wait for redirect to job page
      await page.waitForURL('**/jobs/*', { timeout: 10000 })
    })

    await test.step('navigate to job settings and verify default pay item', async () => {
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
    })
  })
})
