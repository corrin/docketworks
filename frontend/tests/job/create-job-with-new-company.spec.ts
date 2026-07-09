import { test, expect } from '../fixtures/auth'
import {
  autoId,
  dismissToasts,
  submitJobAndWaitForCreatedJob,
  waitForCompanyCreateResponse,
} from '../fixtures/helpers'

/**
 * Tests for creating a job with a new company in Xero.
 * Creates a new company during job creation, verifies Xero sync.
 */

// ============================================================================
// Test Suite: Create Job with New Xero Company
// ============================================================================

test.describe('create job with new xero company', () => {
  test('create new company via Ctrl+Enter and complete job creation', async ({
    authenticatedPage: page,
  }) => {
    // Generate a unique company name with random number
    const randomSuffix = Math.floor(Math.random() * 100000)
    const newCompanyName = `[TEST] Company ${randomSuffix}`
    const jobName = `[TEST] Job for ${newCompanyName}`

    console.log(`Testing with new company: ${newCompanyName}`)

    // Navigate to create job page
    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')
    await expect(autoId(page, 'JobCreateView-title')).toContainText('Create New Job')

    // Type the new company name in the company lookup
    const companyInput = autoId(page, 'CompanyLookup-input')
    await companyInput.fill(newCompanyName)

    // Wait for the dropdown to appear with "Add new company" option
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'CompanyLookup-create-new').waitFor({ timeout: 5000 })

    // Press Ctrl+Enter to quick-create the company (bypasses modal)
    await waitForCompanyCreateResponse(page, async () => {
      await companyInput.press('Control+Enter')
    })

    // Verify company was created - input should still have the company name
    await expect(companyInput).toHaveValue(newCompanyName)

    // Verify the Xero badge shows green (company has Xero ID)
    const xeroIndicator = autoId(page, 'CompanyLookup-xero-valid')
    await expect(xeroIndicator).toBeVisible({ timeout: 10000 })

    console.log(`Company "${newCompanyName}" created with Xero ID`)

    // Fill in the rest of the job form
    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('500')
    await autoId(page, 'JobCreateView-estimated-time').fill('4')

    // Select contact - click the modal button
    await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

    // For a new company, there won't be existing contacts - fill in the create form
    // The form fields are always visible for new companies
    await autoId(page, 'PersonSelectionModal-name-input').fill(`[TEST] Person ${randomSuffix}`)
    await page.waitForTimeout(200)
    await autoId(page, 'PersonSelectionModal-email-input').fill(`test${randomSuffix}@example.com`)
    await page.waitForTimeout(200)

    // Wait for the submit button to be enabled and click it
    const submitButton = autoId(page, 'PersonSelectionModal-submit')
    await expect(submitButton).toBeEnabled({ timeout: 5000 })
    await submitButton.click()

    await autoId(page, 'PersonSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })

    // Set pricing method
    await autoId(page, 'JobCreateView-pricing-method').selectOption('time_materials')

    // Dismiss any toasts that might block the submit button
    await dismissToasts(page)

    const url = await submitJobAndWaitForCreatedJob(page, 'estimate')

    // Verify we're on the job page
    expect(url).toContain('/jobs/')
    expect(url).not.toContain('/create')

    console.log(`Job created successfully at: ${url}`)

    // Verify the job number is displayed - wait for it to be populated
    const jobNumberElement = autoId(page, 'JobView-job-number').first()
    await expect(jobNumberElement).toContainText(/#\d+/, { timeout: 10000 })
    const jobNumberText = await jobNumberElement.innerText()

    console.log(`Created job ${jobNumberText} with new company "${newCompanyName}"`)
  })

  test('create new company via modal and complete job creation', async ({
    authenticatedPage: page,
  }) => {
    // Generate a unique company name with random number
    const randomSuffix = Math.floor(Math.random() * 100000)
    const newCompanyName = `[TEST] Modal Company ${randomSuffix}`
    const jobName = `[TEST] Modal Job ${randomSuffix}`

    console.log(`Testing with new company (modal method): ${newCompanyName}`)

    // Navigate to create job page
    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')

    // Type the new company name
    const companyInput = autoId(page, 'CompanyLookup-input')
    await companyInput.fill(newCompanyName)

    // Wait for dropdown and click "Add new company" - this opens a modal
    await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'CompanyLookup-create-new').click()

    // Wait for the CreateCompanyModal to appear
    const createCompanyModal = page.locator('div[role="dialog"]:has-text("Add New Company")')
    await createCompanyModal.waitFor({ timeout: 5000 })

    console.log('CreateCompanyModal opened')

    // The company name should already be filled in the modal
    // Click "Create Company" button to create the company
    const createCompanyButton = page.getByRole('button', { name: 'Create Company' })
    await waitForCompanyCreateResponse(page, async () => {
      await createCompanyButton.click()
    })

    // Wait for modal to close and company to be created
    await createCompanyModal.waitFor({ state: 'hidden', timeout: 10000 })

    // Verify the Xero badge shows green
    const xeroIndicator = autoId(page, 'CompanyLookup-xero-valid')
    await expect(xeroIndicator).toBeVisible({ timeout: 10000 })

    console.log(`Company "${newCompanyName}" created with Xero ID via modal`)

    // Fill in job details
    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('100')
    await autoId(page, 'JobCreateView-estimated-time').fill('2')

    // Handle person selection
    await autoId(page, 'PersonSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

    // Fill in contact details
    await autoId(page, 'PersonSelectionModal-name-input').fill(
      `[TEST] Modal Contact ${randomSuffix}`,
    )
    await page.waitForTimeout(200)
    await autoId(page, 'PersonSelectionModal-email-input').fill(`modal${randomSuffix}@example.com`)
    await page.waitForTimeout(200)

    const submitButton = autoId(page, 'PersonSelectionModal-submit')
    await expect(submitButton).toBeEnabled({ timeout: 5000 })
    await submitButton.click()

    await autoId(page, 'PersonSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })

    await autoId(page, 'JobCreateView-pricing-method').selectOption('fixed_price')
    await dismissToasts(page)
    const url = await submitJobAndWaitForCreatedJob(page, 'quote')
    expect(url).toContain('/jobs/')

    console.log(`Job created via modal method at: ${url}`)
  })
})
