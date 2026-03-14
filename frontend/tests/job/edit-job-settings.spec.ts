import { test, expect } from '../fixtures/auth'
import { getCompanyDefaults } from '../fixtures/api'
import {
  autoId,
  waitForSettingsInitialized,
  waitForAutosave,
  TEST_CLIENT_NAME,
} from '../fixtures/helpers'

/**
 * Tests for editing a job after creation.
 * Uses the sharedEditJobUrl fixture to create a job once per worker.
 * Each test can run independently with --grep since the fixture handles job creation.
 */
test.describe.serial('edit job', () => {
  test('navigate to Job Settings tab and verify details', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    // Go to the created job
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await test.step('navigate to Job Settings tab', async () => {
      // Click on Job Settings tab
      await autoId(page, 'JobViewTabs-jobSettings').click()

      // Wait for the tab content to load
      await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })

      // Wait for job data to actually populate the fields
      // The field should have a value (not just be empty placeholder)
      const jobNameInput = autoId(page, 'JobSettingsTab-job-name')
      try {
        await expect(jobNameInput).not.toHaveValue('', { timeout: 10000 })
      } catch {
        // If still empty after 10s, log debug info
        const pageText = await page.evaluate(() => document.body.innerText)
        console.log('Page text snippet:', pageText.substring(0, 500))
        throw new Error('Job name field is still empty after 10 seconds - data not loading')
      }
    })

    await test.step('verify job name contains test identifier', async () => {
      const jobNameInput = autoId(page, 'JobSettingsTab-job-name')
      const jobName = await jobNameInput.inputValue()
      console.log('Job name value:', jobName)
      expect(jobName).toContain('Edit Test Job')
    })

    await test.step('verify client is ABC Carpet Cleaning', async () => {
      const clientNameInput = autoId(page, 'JobSettingsTab-client-name')
      await expect(clientNameInput).toHaveValue(TEST_CLIENT_NAME)
    })

    await test.step('verify pricing method is Fixed Price', async () => {
      const pricingSelect = autoId(page, 'JobSettingsTab-pricing-method')
      await expect(pricingSelect).toHaveValue('fixed_price')
    })
  })

  test('change job name', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    // Capture browser console logs for autosave debugging
    page.on('console', (msg) => {
      const text = msg.text()
      if (text.includes('JobAutosave') || text.includes('DEBUG')) {
        console.log(`[Browser] ${text}`)
      }
    })

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    // Navigate to Job Settings tab
    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })

    // Wait for component initialization to complete (so autosave can work)
    await waitForSettingsInitialized(page)

    const newJobName = `Updated Job Name ${Date.now()}`

    await test.step('change the job name', async () => {
      const jobNameInput = autoId(page, 'JobSettingsTab-job-name')
      // Use clear + pressSequentially to ensure @input events fire (fill() doesn't always trigger them)
      await jobNameInput.clear()
      await jobNameInput.pressSequentially(newJobName, { delay: 10 })
      await jobNameInput.blur() // Trigger autosave
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify the name was saved by refreshing', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })

      const jobNameInput = autoId(page, 'JobSettingsTab-job-name')
      await expect(jobNameInput).toHaveValue(newJobName)
    })
  })

  test('change description', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-description').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    const newDescription = `Updated description ${Date.now()}`

    await test.step('change the description', async () => {
      const descInput = autoId(page, 'JobSettingsTab-description')
      await descInput.clear()
      await descInput.pressSequentially(newDescription, { delay: 10 })
      await descInput.blur()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify description was saved', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-description').waitFor({ timeout: 10000 })

      const descInput = autoId(page, 'JobSettingsTab-description')
      await expect(descInput).toHaveValue(newDescription)
    })
  })

  test('change delivery date', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-delivery-date').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    // Set delivery date to 30 days from now
    const futureDate = new Date()
    futureDate.setDate(futureDate.getDate() + 30)
    const dateString = futureDate.toISOString().split('T')[0] // YYYY-MM-DD format

    await test.step('set delivery date', async () => {
      const dateInput = autoId(page, 'JobSettingsTab-delivery-date')
      await dateInput.fill(dateString)
      await dateInput.blur()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify delivery date was saved', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-delivery-date').waitFor({ timeout: 10000 })

      const dateInput = autoId(page, 'JobSettingsTab-delivery-date')
      await expect(dateInput).toHaveValue(dateString)
    })
  })

  test('change order number', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-order-number').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    const newOrderNumber = `ORD-${Date.now()}`

    await test.step('set order number', async () => {
      const orderInput = autoId(page, 'JobSettingsTab-order-number')
      await orderInput.clear()
      await orderInput.pressSequentially(newOrderNumber, { delay: 10 })
      await orderInput.blur()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify order number was saved', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-order-number').waitFor({ timeout: 10000 })

      const orderInput = autoId(page, 'JobSettingsTab-order-number')
      await expect(orderInput).toHaveValue(newOrderNumber)
    })
  })

  test('change speed vs quality', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    // Capture browser console logs for autosave debugging
    page.on('console', (msg) => {
      const text = msg.text()
      if (
        text.includes('JobAutosave') ||
        text.includes('DEBUG') ||
        text.includes('handleFieldInput')
      ) {
        console.log(`[Browser] ${text}`)
      }
    })

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-speed-quality').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('change to quality-focused', async () => {
      const speedQualitySelect = autoId(page, 'JobSettingsTab-speed-quality')
      // Log current value before change
      const beforeValue = await speedQualitySelect.inputValue()
      console.log(`Speed/Quality before change: ${beforeValue}`)

      await speedQualitySelect.selectOption('quality')

      // Log value after change
      const afterValue = await speedQualitySelect.inputValue()
      console.log(`Speed/Quality after change: ${afterValue}`)

      await speedQualitySelect.blur()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify speed vs quality was saved', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-speed-quality').waitFor({ timeout: 10000 })

      const speedQualitySelect = autoId(page, 'JobSettingsTab-speed-quality')
      await expect(speedQualitySelect).toHaveValue('quality')
    })
  })

  test('change internal notes', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-internal-notes').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    const newNotes = `Test internal notes ${Date.now()}`

    await test.step('add internal notes', async () => {
      // Quill editor uses a contenteditable div with class 'ql-editor'
      // Wait for Quill to initialize (it's dynamically imported)
      const notesContainer = autoId(page, 'JobSettingsTab-internal-notes')
      const quillEditor = notesContainer.locator('.ql-editor')
      await quillEditor.waitFor({ timeout: 15000 })
      await quillEditor.click()
      await quillEditor.fill(newNotes)
      // Blur to trigger save
      await page.click('body')
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify internal notes were saved', async () => {
      await page.reload() // Note changing this to goto seems to work!?
      await autoId(page, 'JobViewTabs-jobSettings').waitFor({ timeout: 30000 })
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-internal-notes').waitFor({ timeout: 10000 })

      const notesContainer = autoId(page, 'JobSettingsTab-internal-notes')
      const quillEditor = notesContainer.locator('.ql-editor')
      // Wait for Quill editor to initialize (it loads asynchronously)
      await quillEditor.waitFor({ timeout: 10000 })
      await expect(quillEditor).toContainText(newNotes)
    })
  })

  test('change pricing method from Fixed Price to T&M', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    // Navigate to Job Settings tab
    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-pricing-method').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('change pricing method to Time & Materials', async () => {
      const pricingSelect = autoId(page, 'JobSettingsTab-pricing-method')
      await pricingSelect.selectOption('time_materials')
      await pricingSelect.blur() // Trigger autosave
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify pricing method was saved', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-pricing-method').waitFor({ timeout: 10000 })

      const pricingSelect = autoId(page, 'JobSettingsTab-pricing-method')
      await expect(pricingSelect).toHaveValue('time_materials')
    })
  })

  test('change pricing method from header (T&M back to Fixed Price)', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    // This test uses the InlineEditSelect in the job header area
    // (different UI than the settings tab select)
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await test.step('click on pricing method in header to edit', async () => {
      // Click the display text to enter edit mode
      const pricingDisplay = autoId(page, 'JobView-pricing-method-display')
      await pricingDisplay.waitFor({ timeout: 10000 })
      await pricingDisplay.click()
    })

    await test.step('select Fixed Price from dropdown', async () => {
      const pricingSelect = autoId(page, 'JobView-pricing-method-select')
      await pricingSelect.waitFor({ timeout: 5000 })
      await pricingSelect.selectOption('fixed_price')

      // Click confirm button to save
      const confirmBtn = autoId(page, 'JobView-pricing-method-confirm')
      await confirmBtn.click()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify pricing method was saved', async () => {
      await page.reload()

      // Verify in header display
      const pricingDisplay = autoId(page, 'JobView-pricing-method-display')
      await expect(pricingDisplay).toContainText('Fixed Price', { timeout: 10000 })

      // Also verify in Job Settings tab
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-pricing-method').waitFor({ timeout: 10000 })

      const pricingSelect = autoId(page, 'JobSettingsTab-pricing-method')
      await expect(pricingSelect).toHaveValue('fixed_price')
    })
  })

  test('change job status from header (Draft to In Progress)', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    // Job status is only editable from the header (not in settings tab)
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await test.step('verify initial status is Draft', async () => {
      const statusDisplay = autoId(page, 'JobView-status-display')
      await expect(statusDisplay).toContainText('Draft', { timeout: 10000 })
    })

    await test.step('click on status in header to edit', async () => {
      const statusDisplay = autoId(page, 'JobView-status-display')
      await statusDisplay.click()
    })

    await test.step('select In Progress from dropdown', async () => {
      const statusSelect = autoId(page, 'JobView-status-select')
      await statusSelect.waitFor({ timeout: 5000 })
      await statusSelect.selectOption('in_progress')

      // Click confirm button to save
      const confirmBtn = autoId(page, 'JobView-status-confirm')
      await confirmBtn.click()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify status was saved', async () => {
      await page.reload()

      // Verify in header display
      const statusDisplay = autoId(page, 'JobView-status-display')
      await expect(statusDisplay).toContainText('In Progress', { timeout: 10000 })
    })
  })

  test('change contact person', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    // Navigate to Job Settings tab
    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'ContactSelector-modal-button').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('open contact selection modal', async () => {
      await autoId(page, 'ContactSelector-modal-button').click()
      await autoId(page, 'ContactSelectionModal-container').waitFor({ timeout: 10000 })
    })

    await test.step('create a new contact to switch to', async () => {
      // Wait for the form to be ready
      const submitButton = autoId(page, 'ContactSelectionModal-submit')
      await expect(submitButton).toHaveText('Create Contact', { timeout: 10000 })

      const timestamp = Date.now()
      await autoId(page, 'ContactSelectionModal-name-input').fill(`New Contact ${timestamp}`)
      await autoId(page, 'ContactSelectionModal-email-input').fill(
        `newcontact${timestamp}@example.com`,
      )
      await submitButton.click()

      // Wait for modal to close
      await autoId(page, 'ContactSelectionModal-container').waitFor({
        state: 'hidden',
        timeout: 10000,
      })
    })

    await test.step('verify contact was updated', async () => {
      const contactDisplay = autoId(page, 'ContactSelector-display')
      await expect(contactDisplay).toHaveValue(/New Contact/, { timeout: 10000 })
    })
  })

  test('change client', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    // Get the shop client name from company defaults
    const companyDefaults = await getCompanyDefaults(page)
    const shopClientName = companyDefaults.shop_client_name as string
    expect(shopClientName).toBeTruthy()
    console.log(`Using shop client name: ${shopClientName}`)

    // Navigate to Job Settings tab
    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-change-client-btn').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('click Change Client button', async () => {
      await autoId(page, 'JobSettingsTab-change-client-btn').click()
      await autoId(page, 'JobSettingsTab-client-change-panel').waitFor({ timeout: 5000 })
    })

    await test.step('search for and select a different client', async () => {
      const clientChangePanel = autoId(page, 'JobSettingsTab-client-change-panel')
      const clientInput = clientChangePanel.locator('input[type="text"]')

      // Search using first word of shop client name
      await clientInput.fill(shopClientName.split(' ')[0])
      await page.waitForTimeout(1000) // Allow debounce

      const clientOption = page.getByRole('option', { name: shopClientName, exact: true })
      await clientOption.waitFor({ timeout: 10000 })
      await clientOption.click()
    })

    await test.step('confirm the client change', async () => {
      await autoId(page, 'JobSettingsTab-confirm-client-btn').click()
      await waitForAutosave(page)
    })

    await test.step('verify client was changed', async () => {
      const clientNameInput = autoId(page, 'JobSettingsTab-client-name')
      await expect(clientNameInput).toHaveValue(new RegExp(shopClientName))
    })

    await test.step('verify change persists after refresh', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-client-name').waitFor({ timeout: 10000 })

      const clientNameInput = autoId(page, 'JobSettingsTab-client-name')
      await expect(clientNameInput).toHaveValue(new RegExp(shopClientName))
    })
  })

  test('reload stability - values unchanged after multiple reloads', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    // This test verifies that reloading the page doesn't cause any data drift
    // (i.e., values stay the same and aren't accidentally modified on load)
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    // Capture all field values before reload
    const valuesBefore = await test.step('capture values before reload', async () => {
      return {
        jobName: await autoId(page, 'JobSettingsTab-job-name').inputValue(),
        description: await autoId(page, 'JobSettingsTab-description').inputValue(),
        orderNumber: await autoId(page, 'JobSettingsTab-order-number').inputValue(),
        pricingMethod: await autoId(page, 'JobSettingsTab-pricing-method').inputValue(),
        speedQuality: await autoId(page, 'JobSettingsTab-speed-quality').inputValue(),
        clientName: await autoId(page, 'JobSettingsTab-client-name').inputValue(),
      }
    })

    console.log('Values before reload:', valuesBefore)

    // Reload multiple times to ensure stability
    for (let i = 1; i <= 3; i++) {
      await test.step(`reload #${i} and verify values unchanged`, async () => {
        await page.reload()
        await autoId(page, 'JobViewTabs-jobSettings').click()
        await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })
        await waitForSettingsInitialized(page)

        // Verify all values match
        await expect(autoId(page, 'JobSettingsTab-job-name')).toHaveValue(valuesBefore.jobName)
        await expect(autoId(page, 'JobSettingsTab-description')).toHaveValue(
          valuesBefore.description,
        )
        await expect(autoId(page, 'JobSettingsTab-order-number')).toHaveValue(
          valuesBefore.orderNumber,
        )
        await expect(autoId(page, 'JobSettingsTab-pricing-method')).toHaveValue(
          valuesBefore.pricingMethod,
        )
        await expect(autoId(page, 'JobSettingsTab-speed-quality')).toHaveValue(
          valuesBefore.speedQuality,
        )
        await expect(autoId(page, 'JobSettingsTab-client-name')).toHaveValue(
          valuesBefore.clientName,
        )
      })
    }

    console.log('All 3 reloads completed with no data drift')
  })

  test('change default pay item', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-default-pay-item').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('verify pay item dropdown is visible and has options', async () => {
      const payItemSelect = autoId(page, 'JobSettingsTab-default-pay-item')
      await expect(payItemSelect).toBeVisible()

      // Verify dropdown has at least "Ordinary time" option
      const options = payItemSelect.locator('option')
      const optionCount = await options.count()
      expect(optionCount).toBeGreaterThan(1) // More than just the placeholder
    })

    await test.step('select a different pay item', async () => {
      const payItemSelect = autoId(page, 'JobSettingsTab-default-pay-item')

      // Get available options (skip the first "Select a pay item..." placeholder)
      const options = payItemSelect.locator('option')
      const optionCount = await options.count()

      // Find and select a non-empty option (not the placeholder)
      let selectedValue = ''
      for (let i = 1; i < optionCount; i++) {
        const optionValue = await options.nth(i).getAttribute('value')
        if (optionValue) {
          selectedValue = optionValue
          break
        }
      }

      expect(selectedValue).not.toBe('')
      await payItemSelect.selectOption(selectedValue)
      await payItemSelect.blur()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify pay item was saved', async () => {
      // Get the current value before reload
      const payItemSelect = autoId(page, 'JobSettingsTab-default-pay-item')
      const savedValue = await payItemSelect.inputValue()
      expect(savedValue).not.toBe('')

      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-default-pay-item').waitFor({ timeout: 10000 })

      const payItemSelectAfter = autoId(page, 'JobSettingsTab-default-pay-item')
      await expect(payItemSelectAfter).toHaveValue(savedValue)
    })
  })
})
