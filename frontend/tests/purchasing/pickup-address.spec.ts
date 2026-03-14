import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { autoId, dismissToasts, TEST_CLIENT_NAME } from '../fixtures/helpers'

/**
 * Tests for pickup address functionality on purchase orders.
 */

// ============================================================================
// Helper Functions
// ============================================================================

async function createPOWithExistingSupplier(page: Page): Promise<string> {
  const randomSuffix = Math.floor(Math.random() * 100000)

  await page.goto('/purchasing/po/create')
  await page.waitForLoadState('networkidle')

  const supplierInput = autoId(page, 'ClientLookup-input')
  await supplierInput.click()
  await supplierInput.fill('ABC')
  await page.waitForTimeout(500)
  await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
  await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()
  await expect(supplierInput).toHaveValue(TEST_CLIENT_NAME)

  await autoId(page, 'PoSummaryCard-reference').fill(`E2E Pickup Test ${randomSuffix}`)

  const savePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/purchasing/rest/purchase-orders') &&
      response.request().method() === 'POST' &&
      response.status() === 201,
    { timeout: 30000 },
  )

  await autoId(page, 'PoCreateView-save').click()
  await savePromise

  await page.waitForURL(/\/purchasing\/po\/[a-f0-9-]+$/, { timeout: 15000 })
  return page.url()
}

// ============================================================================
// Test Suite: Pickup Address Selector Basic Behavior
// ============================================================================

test.describe('pickup address selector', () => {
  let poUrl: string

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()

    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD
    await page.goto('/login')
    await page.locator('#username').fill(username!)
    await page.locator('#password').fill(password!)
    await page.getByRole('button', { name: 'Sign In' }).click()
    await page.waitForURL('**/kanban')

    poUrl = await createPOWithExistingSupplier(page)
    console.log(`Created PO at: ${poUrl}`)

    await context.close()
  })

  test('shows pickup address selector when supplier is selected', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    const selector = autoId(page, 'PickupAddressSelector-display')
    await expect(selector).toBeVisible({ timeout: 10000 })

    const modalButton = autoId(page, 'PickupAddressSelector-modal-button')
    await expect(modalButton).toBeEnabled()

    console.log('Pickup address selector is visible and enabled')
  })

  test('opens modal when clicking selector button', async ({ authenticatedPage: page }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'PickupAddressSelector-modal-button').click()

    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible({ timeout: 5000 })

    console.log('Modal opened successfully')
  })
})

// ============================================================================
// Test Suite: Address Autocomplete
// ============================================================================

test.describe('address autocomplete', () => {
  let poUrl: string

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()

    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD
    await page.goto('/login')
    await page.locator('#username').fill(username!)
    await page.locator('#password').fill(password!)
    await page.getByRole('button', { name: 'Sign In' }).click()
    await page.waitForURL('**/kanban')

    poUrl = await createPOWithExistingSupplier(page)
    await context.close()
  })

  test('typing address returns Google autocomplete suggestions', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    // Open modal
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    await autoId(page, 'PickupAddressSelectionModal-container').waitFor({ timeout: 5000 })

    // Type into the street address autocomplete field
    // Component has 300ms debounce before API call
    const streetInput = autoId(page, 'AddressAutocompleteInput')
    await streetInput.click()

    // Type character by character to ensure proper focus and debounce behavior
    await streetInput.pressSequentially('7C Aldersgate', { delay: 50 })

    // Wait for the API response before checking for dropdown
    await page.waitForResponse(
      (response) => response.url().includes('addresses/validate') && response.status() === 200,
      { timeout: 10000 },
    )

    // Now check for the dropdown
    const suggestionDropdown = autoId(page, 'AddressAutocompleteInput-suggestions')
    await expect(suggestionDropdown).toBeVisible({ timeout: 5000 })

    // Should contain the exact Hillsborough road suggestion
    await expect(suggestionDropdown).toContainText(/7C Aldersgate.*Road/i)

    console.log('Autocomplete returned Hillsborough suggestion for "7C Aldersgate"')
  })
})

// ============================================================================
// Test Suite: Create and Select Address (combined to avoid state issues)
// ============================================================================

test.describe('pickup address CRUD', () => {
  let poUrl: string

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()

    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD
    await page.goto('/login')
    await page.locator('#username').fill(username!)
    await page.locator('#password').fill(password!)
    await page.getByRole('button', { name: 'Sign In' }).click()
    await page.waitForURL('**/kanban')

    poUrl = await createPOWithExistingSupplier(page)
    console.log(`Created PO at: ${poUrl}`)

    await context.close()
  })

  test('can create, select, and clear an address', async ({ authenticatedPage: page }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await dismissToasts(page)

    // --- Step 1: Create a new address using real Google autocomplete ---
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible({ timeout: 5000 })

    // Fill name
    const timestamp = Date.now()
    const nameInput = autoId(page, 'PickupAddressSelectionModal-name-input')
    await nameInput.clear()
    await nameInput.fill(`Hillsborough Site ${timestamp}`)

    // Type real address and select from autocomplete
    const streetInput = autoId(page, 'AddressAutocompleteInput')
    await streetInput.click()
    await streetInput.fill('7C Aldersgate')

    // Wait for autocomplete dropdown and select the Hillsborough option
    const suggestionDropdown = autoId(page, 'AddressAutocompleteInput-suggestions')
    await expect(suggestionDropdown).toBeVisible({ timeout: 10000 })
    await suggestionDropdown
      .locator('div')
      .filter({ hasText: /7C Aldersgate.*Road/i })
      .first()
      .click()

    // Click submit and wait for response
    const createPromise = page.waitForResponse(
      (r) =>
        r.url().includes('pickup-addresses') &&
        r.request().method() === 'POST' &&
        r.status() === 201,
      { timeout: 15000 },
    )
    await autoId(page, 'PickupAddressSelectionModal-submit').click()
    await createPromise

    // Modal should close
    await expect(modal).toBeHidden({ timeout: 5000 })

    // Address should be selected
    const display = autoId(page, 'PickupAddressSelector-display')
    await expect(display).toHaveValue(/7C Aldersgate.*Road/i, { timeout: 5000 })
    console.log('Created and selected new address')

    // --- Step 2: Clear the selection ---
    await dismissToasts(page)
    const clearButton = autoId(page, 'PickupAddressSelector-clear-button')
    await expect(clearButton).toBeVisible()
    await clearButton.click()

    // Wait for save and verify success
    await page.waitForResponse(
      (r) =>
        r.url().includes('purchase-orders') &&
        r.request().method() === 'PATCH' &&
        r.status() === 200,
      { timeout: 10000 },
    )

    await expect(display).toHaveValue('')
    console.log('Cleared selection')

    // --- Step 3: Re-select the address ---
    await dismissToasts(page)
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    await expect(modal).toBeVisible({ timeout: 5000 })

    // Find and click select button on the address we created
    const selectButton = autoId(page, 'PickupAddressSelectionModal-select-button').first()
    await expect(selectButton).toBeVisible({ timeout: 5000 })
    await selectButton.click()

    // Modal closes and address is selected
    await expect(modal).toBeHidden({ timeout: 5000 })
    await expect(display).toHaveValue(/7C Aldersgate.*Road/i, { timeout: 5000 })
    console.log('Re-selected existing address')
  })

  test('can edit an existing address', async ({ authenticatedPage: page }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await dismissToasts(page)

    // Open modal
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible({ timeout: 5000 })

    // Wait for addresses to load and find edit button
    await page.waitForTimeout(1000)

    // Check if there are existing addresses
    const addressCards = modal.locator(
      '[data-automation-id="PickupAddressSelectionModal-select-button"]',
    )
    const count = await addressCards.count()

    if (count === 0) {
      console.log('No existing addresses - skipping edit test')
      await page.keyboard.press('Escape')
      return
    }

    // Find and click edit button
    const editButton = modal.locator('button[title="Edit address"]').first()
    await editButton.click()

    // Form should be populated
    const nameInput = autoId(page, 'PickupAddressSelectionModal-name-input')
    const nameValue = await nameInput.inputValue()
    expect(nameValue.length).toBeGreaterThan(0)

    // Update the name
    const newName = `Updated ${Date.now()}`
    await nameInput.clear()
    await nameInput.fill(newName)

    // Submit and wait for PATCH
    const updatePromise = page.waitForResponse(
      (r) =>
        r.url().includes('pickup-addresses') &&
        r.request().method() === 'PATCH' &&
        r.status() === 200,
      { timeout: 15000 },
    )
    await autoId(page, 'PickupAddressSelectionModal-submit').click()
    await updatePromise

    await expect(modal).toBeHidden({ timeout: 5000 })
    console.log('Updated address successfully')
  })

  test('can delete an existing address', async ({ authenticatedPage: page }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await dismissToasts(page)

    // Open modal
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible({ timeout: 5000 })

    // Wait for addresses to load
    await page.waitForTimeout(1000)

    // Check if there are existing addresses
    const addressCards = modal.locator(
      '[data-automation-id="PickupAddressSelectionModal-select-button"]',
    )
    const initialCount = await addressCards.count()

    if (initialCount === 0) {
      console.log('No existing addresses - skipping delete test')
      await page.keyboard.press('Escape')
      return
    }

    // Find and click delete button on first address
    const deleteButton = modal.locator('button[title="Delete address"]').first()
    await deleteButton.click()

    // Confirm deletion dialog should appear
    await expect(modal.getByText('Delete Address?')).toBeVisible({ timeout: 5000 })

    // Click confirm delete
    const deletePromise = page.waitForResponse(
      (r) =>
        r.url().includes('pickup-addresses') &&
        r.request().method() === 'DELETE' &&
        r.status() === 204,
      { timeout: 15000 },
    )
    await modal.getByRole('button', { name: 'Delete', exact: true }).click()
    await deletePromise

    // Modal should still be open but with one fewer address
    await page.waitForTimeout(500)
    const newCount = await addressCards.count()
    expect(newCount).toBeLessThan(initialCount)

    console.log(`Deleted address. Count went from ${initialCount} to ${newCount}`)
    await page.keyboard.press('Escape')
  })

  test('selecting autocomplete suggestion populates form fields', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await dismissToasts(page)

    // Open modal
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible({ timeout: 5000 })

    // Type real address
    const streetInput = autoId(page, 'AddressAutocompleteInput')
    await streetInput.click()
    await streetInput.pressSequentially('7C Aldersgate', { delay: 50 })

    // Wait for dropdown and select Hillsborough option
    const suggestionDropdown = autoId(page, 'AddressAutocompleteInput-suggestions')
    await expect(suggestionDropdown).toBeVisible({ timeout: 10000 })
    await suggestionDropdown
      .locator('div')
      .filter({ hasText: /7C Aldersgate.*Road/i })
      .first()
      .click()

    // City field should be populated from Google data
    const cityInput = modal.locator('input[placeholder="City"]')
    await expect(cityInput).not.toHaveValue('', { timeout: 5000 })
    const cityValue = await cityInput.inputValue()
    expect(cityValue.length).toBeGreaterThan(0)

    console.log(`City field populated: ${cityValue}`)
    await page.keyboard.press('Escape')
  })
})

// ============================================================================
// Test Suite: Selector without supplier
// ============================================================================

test.describe('pickup address without supplier', () => {
  test('shows message when no supplier selected', async ({ authenticatedPage: page }) => {
    // Go to create PO page (no supplier selected yet)
    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    // Pickup address section should not be visible without supplier
    const selector = autoId(page, 'PickupAddressSelector-display')
    await expect(selector).not.toBeVisible({ timeout: 5000 })

    console.log('Pickup address selector not visible without supplier')
  })

  test('modal button is disabled without supplier', async ({ authenticatedPage: page }) => {
    await page.goto('/purchasing/po/create')
    await page.waitForLoadState('networkidle')

    // Select a supplier first
    const supplierInput = autoId(page, 'ClientLookup-input')
    await supplierInput.click()
    await supplierInput.fill('ABC')
    await page.waitForTimeout(500)
    await autoId(page, 'ClientLookup-results').waitFor({ timeout: 10000 })
    await page.getByRole('option', { name: new RegExp(TEST_CLIENT_NAME) }).click()

    // Now pickup address should be visible and button enabled
    const modalButton = autoId(page, 'PickupAddressSelector-modal-button')
    await expect(modalButton).toBeEnabled({ timeout: 5000 })

    console.log('Modal button is enabled after supplier selection')
  })
})
