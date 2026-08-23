import { test, expect } from '../fixtures/auth'
import { autoId, createTestPurchaseOrder, dismissToasts, TEST_COMPANY_NAME } from '../helpers'

/**
 * Pickup addresses on a purchase order: the supplier's addresses are chosen,
 * created, edited and deleted from the PO, and the street field offers real
 * candidates from Google Address Validation through the backend proxy (the
 * key lives on IntegrationSettings; the preflight proves it). Serial over one
 * PO whose supplier is created fresh, so the address list starts empty and
 * every step sees exactly what the previous one left.
 */

/** A real Hillsborough, Auckland address; Google must resolve it for the run to be valid. */
const PROBE_STREET = '7C Aldersgate'
const PROBE_MATCH = /7C Aldersgate.*Road/i

test.describe.serial('pickup addresses', () => {
  let poUrl: string

  test('the Purchases menu reaches the purchase-order list', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/kanban')
    await autoId(page, 'AppNavbar-purchases-menu').click()
    await autoId(page, 'AppNavbar-purchase-orders').click()
    await expect(page).toHaveURL(/\/purchasing\/po\/?$/)
  })

  test('a PO with a supplier offers the selector', async ({ authenticatedPage: page }) => {
    poUrl = await createTestPurchaseOrder(page)

    await expect(autoId(page, 'PickupAddressSelector-display')).toBeVisible()
    await expect(autoId(page, 'PickupAddressSelector-modal-button')).toBeEnabled()
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    await expect(autoId(page, 'PickupAddressSelectionModal-container')).toBeVisible()
  })

  test('typing a street returns a Google candidate', async ({ authenticatedPage: page }) => {
    await page.goto(poUrl)
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    await autoId(page, 'PickupAddressSelectionModal-container').waitFor()

    const street = autoId(page, 'AddressAutocompleteInput')
    await street.click()
    const validated = page.waitForResponse(
      (response) =>
        response.url().includes('/addresses/validate/') && response.request().method() === 'POST',
    )
    await street.pressSequentially(PROBE_STREET, { delay: 50 })
    expect((await validated).ok()).toBe(true)

    const suggestions = autoId(page, 'AddressAutocompleteInput-suggestions')
    await expect(suggestions).toBeVisible()
    await expect(suggestions).toContainText(PROBE_MATCH)
  })

  test('an address is created, selected, cleared and re-selected', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await dismissToasts(page)
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible()

    await autoId(page, 'PickupAddressSelectionModal-name-input').fill(
      `Hillsborough Site ${Date.now()}`,
    )
    const street = autoId(page, 'AddressAutocompleteInput')
    await street.click()
    await street.pressSequentially(PROBE_STREET, { delay: 50 })
    const suggestions = autoId(page, 'AddressAutocompleteInput-suggestions')
    await expect(suggestions).toBeVisible()
    await suggestions.locator('div').filter({ hasText: PROBE_MATCH }).first().click()
    // The candidate fills the rest of the form.
    await expect(modal.locator('input[placeholder="City"]')).not.toHaveValue('')

    const created = page.waitForResponse(
      (response) =>
        response.url().includes('/pickup-addresses/') &&
        response.request().method() === 'POST' &&
        response.status() === 201,
    )
    const linked = page.waitForResponse(
      (response) =>
        response.url().includes('/purchase-orders/') &&
        response.request().method() === 'PATCH' &&
        response.status() === 200,
    )
    await autoId(page, 'PickupAddressSelectionModal-submit').click()
    await created
    await linked
    await expect(modal).toBeHidden()
    const display = autoId(page, 'PickupAddressSelector-display')
    await expect(display).toHaveValue(PROBE_MATCH)
    // The link survives a reload: the PATCH carried pickup_address_id.
    await page.reload()
    await expect(autoId(page, 'PickupAddressSelector-display')).toHaveValue(PROBE_MATCH)

    // Clear sends an explicit null (ADR 0040) and empties the display.
    await dismissToasts(page)
    const cleared = page.waitForResponse(
      (response) =>
        response.url().includes('/purchase-orders/') &&
        response.request().method() === 'PATCH' &&
        response.status() === 200,
    )
    await autoId(page, 'PickupAddressSelector-clear-button').click()
    const clearBody: unknown = (await cleared).request().postDataJSON()
    expect(clearBody).toEqual({ pickup_address_id: null })
    await expect(autoId(page, 'PickupAddressSelector-display')).toHaveValue('')

    // Re-select the address from the list.
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    await expect(modal).toBeVisible()
    await autoId(page, 'PickupAddressSelectionModal-select-button').first().click()
    await expect(modal).toBeHidden()
    await expect(autoId(page, 'PickupAddressSelector-display')).toHaveValue(PROBE_MATCH)
  })

  test('an existing address is edited', async ({ authenticatedPage: page }) => {
    await page.goto(poUrl)
    await dismissToasts(page)
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible()
    await expect(autoId(page, 'PickupAddressSelectionModal-select-button').first()).toBeVisible()

    await modal.locator('button[title="Edit address"]').first().click()
    const name = autoId(page, 'PickupAddressSelectionModal-name-input')
    expect((await name.inputValue()).length).toBeGreaterThan(0)
    const newName = `Updated ${Date.now()}`
    await name.fill(newName)

    const updated = page.waitForResponse(
      (response) =>
        response.url().includes('/pickup-addresses/') &&
        response.request().method() === 'PATCH' &&
        response.status() === 200,
    )
    await autoId(page, 'PickupAddressSelectionModal-submit').click()
    await updated
    await expect(modal).toBeHidden()

    await autoId(page, 'PickupAddressSelector-modal-button').click()
    await expect(modal).toContainText(newName)
  })

  test('an existing address is deleted', async ({ authenticatedPage: page }) => {
    await page.goto(poUrl)
    await dismissToasts(page)
    await autoId(page, 'PickupAddressSelector-modal-button').click()
    const modal = autoId(page, 'PickupAddressSelectionModal-container')
    await expect(modal).toBeVisible()
    const cards = autoId(page, 'PickupAddressSelectionModal-select-button')
    await expect(cards.first()).toBeVisible()
    const before = await cards.count()

    await modal.locator('button[title="Delete address"]').first().click()
    await expect(modal.getByText('Delete Address?')).toBeVisible()
    const deleted = page.waitForResponse(
      (response) =>
        response.url().includes('/pickup-addresses/') &&
        response.request().method() === 'DELETE' &&
        response.status() === 204,
    )
    await modal.getByRole('button', { name: 'Delete', exact: true }).click()
    await deleted

    await expect(modal).toBeVisible()
    await expect(cards).toHaveCount(before - 1)
  })

  test('the create page offers the selector only once a supplier is chosen', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/purchasing/po/create')
    await expect(autoId(page, 'PickupAddressSelector-display')).toHaveCount(0)

    const supplierInput = autoId(page, 'CompanyLookup-input')
    await supplierInput.click()
    await supplierInput.fill('ABC')
    await autoId(page, 'CompanyLookup-results').waitFor()
    await page.getByRole('option', { name: new RegExp(TEST_COMPANY_NAME) }).click()

    await expect(autoId(page, 'PickupAddressSelector-modal-button')).toBeEnabled()
  })
})
