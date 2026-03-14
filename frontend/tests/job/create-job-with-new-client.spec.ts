import { test, expect } from '../fixtures/auth'
import { autoId, dismissToasts } from '../fixtures/helpers'

/**
 * Tests for creating a job with a new client in Xero.
 * Creates a new client during job creation, verifies Xero sync.
 */

// ============================================================================
// Test Suite: Create Job with New Xero Client
// ============================================================================

test.describe('create job with new xero client', () => {
  test('create new client via Ctrl+Enter and complete job creation', async ({
    authenticatedPage: page,
  }) => {
    // Generate a unique client name with random number
    const randomSuffix = Math.floor(Math.random() * 100000)
    const newClientName = `E2E Test Client ${randomSuffix}`
    const jobName = `Test Job for ${newClientName}`

    console.log(`Testing with new client: ${newClientName}`)

    // Navigate to create job page
    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')
    await expect(autoId(page, 'JobCreateView-title')).toContainText('Create New Job')

    // Type the new client name in the client lookup
    const clientInput = autoId(page, 'ClientLookup-input')
    await clientInput.fill(newClientName)

    // Wait for the dropdown to appear with "Add new client" option
    await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'ClientLookup-create-new').waitFor({ timeout: 5000 })

    // Press Ctrl+Enter to quick-create the client (bypasses modal)
    await clientInput.press('Control+Enter')

    // Wait for client creation - there should be a success toast
    await page.waitForTimeout(3000)

    // Verify client was created - input should still have the client name
    await expect(clientInput).toHaveValue(newClientName)

    // Verify the Xero badge shows green (client has Xero ID)
    const xeroIndicator = autoId(page, 'ClientLookup-xero-valid')
    await expect(xeroIndicator).toBeVisible({ timeout: 10000 })

    console.log(`Client "${newClientName}" created with Xero ID`)

    // Fill in the rest of the job form
    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('500')
    await autoId(page, 'JobCreateView-estimated-time').fill('4')

    // Select contact - click the modal button
    await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })

    // For a new client, there won't be existing contacts - fill in the create form
    // The form fields are always visible for new clients
    await autoId(page, 'ContactSelectionModal-name-input').fill(`Contact for ${randomSuffix}`)
    await page.waitForTimeout(200)
    await autoId(page, 'ContactSelectionModal-email-input').fill(`test${randomSuffix}@example.com`)
    await page.waitForTimeout(200)

    // Wait for the submit button to be enabled and click it
    const submitButton = autoId(page, 'ContactSelectionModal-submit')
    await expect(submitButton).toBeEnabled({ timeout: 5000 })
    await submitButton.click()

    await autoId(page, 'ContactSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })

    // Set pricing method
    await autoId(page, 'JobCreateView-pricing-method').selectOption('time_materials')

    // Dismiss any toasts that might block the submit button
    await dismissToasts(page)

    // Submit the job
    await autoId(page, 'JobCreateView-submit').click({ force: true })

    // Wait for redirect to job edit view
    await page.waitForURL('**/jobs/*?*tab=estimate*', { timeout: 15000 })

    // Verify we're on the job page
    const url = page.url()
    expect(url).toContain('/jobs/')
    expect(url).not.toContain('/create')

    console.log(`Job created successfully at: ${url}`)

    // Verify the job number is displayed - wait for it to be populated
    const jobNumberElement = autoId(page, 'JobView-job-number').first()
    await expect(jobNumberElement).toContainText(/#\d+/, { timeout: 10000 })
    const jobNumberText = await jobNumberElement.innerText()

    console.log(`Created job ${jobNumberText} with new client "${newClientName}"`)
  })

  test('create new client via modal and complete job creation', async ({
    authenticatedPage: page,
  }) => {
    // Generate a unique client name with random number
    const randomSuffix = Math.floor(Math.random() * 100000)
    const newClientName = `E2E Modal Client ${randomSuffix}`
    const jobName = `Modal Test Job ${randomSuffix}`

    console.log(`Testing with new client (modal method): ${newClientName}`)

    // Navigate to create job page
    await autoId(page, 'AppNavbar-create-job').click()
    await page.waitForURL('**/jobs/create')

    // Type the new client name
    const clientInput = autoId(page, 'ClientLookup-input')
    await clientInput.fill(newClientName)

    // Wait for dropdown and click "Add new client" - this opens a modal
    await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
    await autoId(page, 'ClientLookup-create-new').click()

    // Wait for the CreateClientModal to appear
    const createClientModal = page.locator('div[role="dialog"]:has-text("Add New Client")')
    await createClientModal.waitFor({ timeout: 5000 })

    console.log('CreateClientModal opened')

    // The client name should already be filled in the modal
    // Click "Create Client" button to create the client
    const createClientButton = page.getByRole('button', { name: 'Create Client' })
    await createClientButton.click()

    // Wait for modal to close and client to be created
    await createClientModal.waitFor({ state: 'hidden', timeout: 10000 })
    await page.waitForTimeout(1000)

    // Verify the Xero badge shows green
    const xeroIndicator = autoId(page, 'ClientLookup-xero-valid')
    await expect(xeroIndicator).toBeVisible({ timeout: 10000 })

    console.log(`Client "${newClientName}" created with Xero ID via modal`)

    // Fill in job details
    await autoId(page, 'JobCreateView-name-input').fill(jobName)
    await autoId(page, 'JobCreateView-estimated-materials').fill('100')
    await autoId(page, 'JobCreateView-estimated-time').fill('2')

    // Handle contact selection
    await autoId(page, 'ContactSelector-modal-button').click({ timeout: 10000 })
    await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })

    // Fill in contact details
    await autoId(page, 'ContactSelectionModal-name-input').fill(`Modal Contact ${randomSuffix}`)
    await page.waitForTimeout(200)
    await autoId(page, 'ContactSelectionModal-email-input').fill(`modal${randomSuffix}@example.com`)
    await page.waitForTimeout(200)

    const submitButton = autoId(page, 'ContactSelectionModal-submit')
    await expect(submitButton).toBeEnabled({ timeout: 5000 })
    await submitButton.click()

    await autoId(page, 'ContactSelectionModal-container').waitFor({
      state: 'hidden',
      timeout: 10000,
    })

    await autoId(page, 'JobCreateView-pricing-method').selectOption('fixed_price')
    await dismissToasts(page)
    await autoId(page, 'JobCreateView-submit').click({ force: true })

    // For fixed_price jobs, redirect goes to quote tab
    await page.waitForURL('**/jobs/*?*tab=quote*', { timeout: 15000 })

    const url = page.url()
    expect(url).toContain('/jobs/')

    console.log(`Job created via modal method at: ${url}`)
  })
})
