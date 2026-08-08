import debug from 'debug'
import { test, expect } from '../fixtures/auth'
import {
  autoId,
  dismissToasts,
  submitJobAndWaitForCreatedJob,
  waitForCompanyCreateResponse,
} from '../helpers'

const log = debug('e2e:job')

/**
 * Creating a job for a company that does not exist yet: the lookup's
 * quick-create (Ctrl+Enter) and modal paths both round-trip through the
 * accounting provider — the Xero badge turning green is the assertion that
 * the company came back with a xero_contact_id.
 */

test.describe('create job with new xero company', () => {
  test('create new company via Ctrl+Enter and complete job creation', async ({
    authenticatedPage: page,
  }) => {
    const randomSuffix = Math.floor(Math.random() * 100000)
    const newCompanyName = `[TEST] Company ${randomSuffix}`
    const jobName = `[TEST] Job for ${newCompanyName}`

    log(`Testing with new company: ${newCompanyName}`)

    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')
    await expect(autoId(page, 'JobCreateView-title')).toContainText('Create New Job')

    // Type the new company name in the company lookup
    const companyInput = autoId(page, 'CompanyLookup-input')
    await companyInput.fill(newCompanyName)

    // Wait for the dropdown with the "Add new company" option
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'CompanyLookup-create-new').waitFor({ timeout: 5000 })

    // Ctrl+Enter quick-creates the company (bypasses the modal)
    await waitForCompanyCreateResponse(page, async () => {
      await companyInput.press('Control+Enter')
    })

    // The created company is selected — the input shows its name
    await expect(companyInput).toHaveValue(newCompanyName)

    // The Xero badge goes green: the company has a xero_contact_id
    await expect(autoId(page, 'CompanyLookup-xero-valid')).toBeVisible({ timeout: 10000 })

    log(`Company "${newCompanyName}" created with Xero ID`)

    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('500')
    await autoId(page, 'JobCreateView-estimated-time').fill('4')

    // A brand-new company has no people; create one in the modal
    await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-name-input').fill(`[TEST] Person ${randomSuffix}`)
    await autoId(page, 'PersonSelectionModal-email-input').fill(`test${randomSuffix}@example.com`)
    const personSubmit = autoId(page, 'PersonSelectionModal-submit')
    await expect(personSubmit).toBeEnabled({ timeout: 5000 })
    await personSubmit.click()
    await autoId(page, 'PersonSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })

    await autoId(page, 'JobCreateView-pricing-method').selectOption('time_materials')
    await dismissToasts(page)

    const url = await submitJobAndWaitForCreatedJob(page, 'estimate')
    expect(url).toContain('/jobs/')
    expect(url).not.toContain('/create')

    const jobNumberElement = autoId(page, 'JobView-job-number').first()
    await expect(jobNumberElement).toContainText(/#\d+/, { timeout: 10000 })
    log(`Created job ${await jobNumberElement.innerText()} with new company "${newCompanyName}"`)
  })

  test('create new company via modal and complete job creation', async ({
    authenticatedPage: page,
  }) => {
    const randomSuffix = Math.floor(Math.random() * 100000)
    const newCompanyName = `[TEST] Modal Company ${randomSuffix}`
    const jobName = `[TEST] Modal Job ${randomSuffix}`

    log(`Testing with new company (modal method): ${newCompanyName}`)

    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')

    const companyInput = autoId(page, 'CompanyLookup-input')
    await companyInput.fill(newCompanyName)

    // Click "Add new company" — this opens the CreateCompanyModal
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'CompanyLookup-create-new').click()

    const createCompanyModal = page.locator('div[role="dialog"]:has-text("Add New Company")')
    await createCompanyModal.waitFor({ timeout: 5000 })

    log('CreateCompanyModal opened')

    // The name is prefilled from the query; create straight away
    const createCompanyButton = page.getByRole('button', { name: 'Create Company' })
    await waitForCompanyCreateResponse(page, async () => {
      await createCompanyButton.click()
    })

    await createCompanyModal.waitFor({ state: 'hidden', timeout: 10000 })

    await expect(autoId(page, 'CompanyLookup-xero-valid')).toBeVisible({ timeout: 10000 })

    log(`Company "${newCompanyName}" created with Xero ID via modal`)

    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('100')
    await autoId(page, 'JobCreateView-estimated-time').fill('2')

    await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-name-input').fill(
      `[TEST] Modal Person ${randomSuffix}`,
    )
    await autoId(page, 'PersonSelectionModal-email-input').fill(`modal${randomSuffix}@example.com`)
    const personSubmit = autoId(page, 'PersonSelectionModal-submit')
    await expect(personSubmit).toBeEnabled({ timeout: 5000 })
    await personSubmit.click()
    await autoId(page, 'PersonSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })

    await autoId(page, 'JobCreateView-pricing-method').selectOption('fixed_price')
    await dismissToasts(page)

    const url = await submitJobAndWaitForCreatedJob(page, 'quote')
    expect(url).toContain('/jobs/')
  })
})
