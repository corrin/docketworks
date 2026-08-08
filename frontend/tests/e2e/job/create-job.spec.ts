import debug from 'debug'
import { test, expect } from '../fixtures/auth'
import {
  autoId,
  dismissToasts,
  submitJobAndWaitForCreatedJob,
  TEST_COMPANY_NAME,
  waitForSettingsInitialized,
} from '../helpers'

const log = debug('e2e:job')

/**
 * Sequential test cases for job creation. These MUST run in order — each
 * builds on the people the previous test created for the seed company:
 * - Test 1: Company has 0 people → creates first person (becomes primary)
 * - Test 2: Company has 1 person → creates second person
 * - Test 3: Company has 2 people → selects the non-primary person
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
    personToSelect: '[TEST] Another Person',
    expectedTab: 'quote',
  },
] as const

test.describe.serial('create job', () => {
  for (const tc of jobTestCases) {
    test(`create ${tc.name} job with company and person`, async ({ authenticatedPage: page }) => {
      const timestamp = Date.now()
      const jobName = `[TEST] Job ${tc.name} ${timestamp}`

      await test.step('navigate to create job page', async () => {
        await autoId(page, 'AppNavbar-create-job').click()
        await page.waitForURL('**/jobs/create')
        await expect(autoId(page, 'JobCreateView-title')).toContainText('Create New Job')
      })

      await test.step('search and select company', async () => {
        log('Searching for company ABC...')
        const companyInput = autoId(page, 'CompanyLookup-input')
        await companyInput.fill('ABC')

        await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })

        log(`Selecting ${TEST_COMPANY_NAME}...`)
        await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()

        await expect(companyInput).toHaveValue(TEST_COMPANY_NAME)
      })

      await test.step('enter job name', async () => {
        await autoId(page, 'JobCreateView-name-input').fill(jobName)
      })

      await test.step('select or create person', async () => {
        log('Opening person modal...')
        await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })

        log('Waiting for modal...')
        await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

        // Narrow on the createPerson discriminant alone: every createPerson
        // case carries personToCreate, and TS cannot narrow the else branch
        // of a compound `A && B` condition.
        if (tc.createPerson) {
          log(`Creating new person: ${tc.personToCreate.name}`)

          // "Create Person" (not "Saving...") is what marks the form ready.
          const submitButton = autoId(page, 'PersonSelectionModal-submit')
          await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })

          await autoId(page, 'PersonSelectionModal-name-input').fill(tc.personToCreate.name)
          await autoId(page, 'PersonSelectionModal-email-input').fill(tc.personToCreate.email)

          await submitButton.click()
        } else {
          log(`Selecting existing person: ${tc.personToSelect}`)
          await autoId(page, 'PersonSelectionModal-select-button')
            .first()
            .waitFor({ timeout: 10000 })

          // The Select button sits in a hover-revealed overlay on the card.
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

        log('Waiting for modal to close...')
        await autoId(page, 'PersonSelectionModal-container').waitFor({
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
        log(`Submitting job ${jobName}...`)

        // Toasts from person creation can overlap the submit button.
        await dismissToasts(page)

        const url = await submitJobAndWaitForCreatedJob(page, tc.expectedTab)

        expect(url).toContain('/jobs/')
        expect(url).toContain(`tab=${tc.expectedTab}`)

        log(`Successfully created ${tc.name} job: ${jobName}`)
      })
    })
  }
})

test.describe('new job default pay item', () => {
  test('newly created job defaults to Ordinary time pay item', async ({
    authenticatedPage: page,
  }) => {
    const timestamp = Date.now()
    const jobName = `[TEST] Pay Item Job ${timestamp}`

    await test.step('create a new job', async () => {
      await autoId(page, 'AppNavbar-create-job').click()
      await page.waitForURL('**/jobs/create')

      const companyInput = autoId(page, 'CompanyLookup-input')
      await companyInput.fill('ABC')
      await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
      await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()

      await autoId(page, 'JobCreateView-name-input').fill(jobName)

      await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
      await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

      // Runs standalone or after the serial block, so the company may or may
      // not already have people — select one if present, else create one.
      const selectButtons = autoId(page, 'PersonSelectionModal-select-button')
      const hasExistingPeople = (await selectButtons.count()) > 0

      if (hasExistingPeople) {
        await selectButtons.first().click()
      } else {
        const submitButton = autoId(page, 'PersonSelectionModal-submit')
        await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })
        await autoId(page, 'PersonSelectionModal-name-input').fill(`[TEST] Person ${timestamp}`)
        await autoId(page, 'PersonSelectionModal-email-input').fill(`test${timestamp}@example.com`)
        await submitButton.click()
      }

      await autoId(page, 'PersonSelectionModal-container').waitFor({
        state: 'hidden',
        timeout: 10000,
      })

      await autoId(page, 'JobCreateView-estimated-materials').fill('100')
      await autoId(page, 'JobCreateView-estimated-time').fill('2')

      await dismissToasts(page)
      await submitJobAndWaitForCreatedJob(page, 'estimate')
    })

    await test.step('navigate to job settings and verify default pay item', async () => {
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-default-pay-item').waitFor({ timeout: 10000 })
      await waitForSettingsInitialized(page)

      const payItemSelect = autoId(page, 'JobSettingsTab-default-pay-item')
      const selectedText = await payItemSelect.locator('option:checked').textContent()

      expect(selectedText).toBe('Ordinary Time')
    })
  })
})
