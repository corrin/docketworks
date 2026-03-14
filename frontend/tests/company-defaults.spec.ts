import { test, expect } from './fixtures/auth'

test('test can call backend API directly', async ({ authenticatedPage: page }) => {
  const apiBaseUrl = process.env.VITE_API_BASE_URL
  if (!apiBaseUrl) {
    throw new Error('VITE_API_BASE_URL must be set in .env')
  }

  // Get auth method and build headers accordingly
  const authMethod = process.env.VITE_AUTH_METHOD
  const headers: Record<string, string> = {
    'ngrok-skip-browser-warning': 'true',
    Accept: 'application/json',
  }

  // For bearer auth, retrieve token from localStorage and add Authorization header
  // For cookie auth, the browser session handles auth automatically via page.request
  if (authMethod === 'bearer') {
    const token = await page.evaluate(() => localStorage.getItem('auth_token'))
    if (!token) {
      throw new Error('No auth token found in localStorage after login')
    }
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await page.request.get(`${apiBaseUrl}/api/company-defaults/`, { headers })

  console.log(`API response status: ${response.status()}`)

  // If we get HTML back, log it for debugging
  const contentType = response.headers()['content-type'] || ''
  if (!contentType.includes('application/json')) {
    const text = await response.text()
    console.log(`Unexpected content-type: ${contentType}`)
    console.log(`Response body (first 500 chars): ${text.substring(0, 500)}`)
  }

  expect(response.ok()).toBeTruthy()
  expect(contentType).toContain('application/json')

  const data = await response.json()
  expect(data.test_client_name).toBeDefined()
  expect(data.test_client_name).not.toBe('')

  console.log(`Test client name from API: ${data.test_client_name}`)
})

test('test company defaults edit and save', async ({ authenticatedPage: page }) => {
  // Navigate to the admin company page
  await page.goto('/admin/company')

  // Wait for the section buttons to load
  await page.waitForSelector('[data-automation-id="AdminCompanyView-company-button"]', {
    timeout: 15000,
  })

  // Click Company section to open modal
  await page.click('[data-automation-id="AdminCompanyView-company-button"]')

  // Wait for modal to open
  const modal = page.locator('[data-automation-id="SectionModal-content"]')
  await expect(modal).toBeVisible({ timeout: 10000 })

  // Find the company email input (company_name is readonly)
  const companyEmailInput = page.locator(
    '[data-automation-id="SectionModal-company-field-company_email"]',
  )
  await expect(companyEmailInput).toBeVisible()

  // Get the original value
  const originalValue = await companyEmailInput.inputValue()
  console.log(`Original company email: ${originalValue}`)

  // Change to a test value with timestamp
  const testValue = `test${Date.now()}@example.com`
  await companyEmailInput.clear()
  await companyEmailInput.fill(testValue)
  await page.keyboard.press('Tab') // Blur to ensure v-model syncs
  await page.waitForTimeout(500) // Wait for Vue reactivity to propagate
  console.log(`Changed company email to: ${testValue}`)

  // Close the modal
  await page.click('[data-automation-id="SectionModal-company-close-button"]')

  // Wait for modal to close
  await expect(modal).not.toBeVisible({ timeout: 5000 })

  // Click Save All
  await page.click('[data-automation-id="AdminCompanyView-save-all-button"]')

  // Wait for save to complete (toast appears)
  await page.waitForTimeout(1500)

  // Reopen the Company section
  await page.click('[data-automation-id="AdminCompanyView-company-button"]')
  await page.waitForSelector('[data-automation-id="SectionModal-content"]', { timeout: 10000 })

  // Verify the value persisted
  const savedInput = page.locator('[data-automation-id="SectionModal-company-field-company_email"]')
  const savedValue = await savedInput.inputValue()
  console.log(`Saved company email: ${savedValue}`)
  expect(savedValue).toBe(testValue)

  // Restore original value
  await savedInput.clear()
  await savedInput.fill(originalValue)

  // Close modal and save
  await page.click('[data-automation-id="SectionModal-company-close-button"]')
  await expect(page.locator('[data-automation-id="SectionModal-content"]')).not.toBeVisible({
    timeout: 5000,
  })
  await page.click('[data-automation-id="AdminCompanyView-save-all-button"]')

  console.log(`Restored company email to: ${originalValue}`)
})
