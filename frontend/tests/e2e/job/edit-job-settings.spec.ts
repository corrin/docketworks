import debug from 'debug'
import { test, expect } from '../fixtures/auth'
import { getCompanyDefaults, isRecord } from '../fixtures/api'
import {
  autoId,
  getJobIdFromUrl,
  waitForSettingsInitialized,
  waitForAutosave,
  createTestJob,
  TEST_COMPANY_NAME,
} from '../helpers'

const log = debug('e2e:job')

interface JobHeaderSnapshot {
  person_id: string | null
  person_name: string | null
}

function parseJobHeader(payload: unknown): JobHeaderSnapshot {
  if (!isRecord(payload)) {
    throw new Error(`Job header response was not an object: ${JSON.stringify(payload)}`)
  }
  const personId = payload.person_id
  const personName = payload.person_name
  if (personId !== null && typeof personId !== 'string') {
    throw new Error(`Job header person_id has unexpected type: ${JSON.stringify(personId)}`)
  }
  if (personName !== null && typeof personName !== 'string') {
    throw new Error(`Job header person_name has unexpected type: ${JSON.stringify(personName)}`)
  }
  return { person_id: personId, person_name: personName }
}

/**
 * Tests for editing a job after creation, sharing one fixture job per worker.
 * The describe is SERIAL and order-dependent: later tests assume the values
 * earlier tests left behind (test 8 sets time_materials, test 9 flips it
 * back from the header).
 */
test.describe.serial('edit job', () => {
  test('navigate to Job Settings tab and verify details', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await test.step('navigate to Job Settings tab', async () => {
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })

      const jobNameInput = autoId(page, 'JobSettingsTab-job-name')
      await expect(jobNameInput).not.toHaveValue('', { timeout: 10000 })
    })

    await test.step('verify job name contains test identifier', async () => {
      const jobNameInput = autoId(page, 'JobSettingsTab-job-name')
      const jobName = await jobNameInput.inputValue()
      expect(jobName).toContain('[TEST] Edit Job')
    })

    await test.step('verify company is ABC Carpet Cleaning', async () => {
      const companyNameInput = autoId(page, 'JobSettingsTab-company-name')
      await expect(companyNameInput).toHaveValue(TEST_COMPANY_NAME)
    })

    await test.step('verify pricing method is Fixed Price', async () => {
      const pricingSelect = autoId(page, 'JobSettingsTab-pricing-method')
      await expect(pricingSelect).toHaveValue('fixed_price')
    })
  })

  test('change job name', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    const newJobName = `Updated Job Name ${Date.now()}`

    await test.step('change the job name', async () => {
      const jobNameInput = autoId(page, 'JobSettingsTab-job-name')
      // clear + pressSequentially so per-keystroke input events fire
      await jobNameInput.clear()
      await jobNameInput.pressSequentially(newJobName, { delay: 10 })
      await jobNameInput.blur()
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

    const futureDate = new Date()
    futureDate.setDate(futureDate.getDate() + 30)
    const dateString = futureDate.toISOString().split('T')[0] ?? ''

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
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-speed-quality').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('change to quality-focused', async () => {
      const speedQualitySelect = autoId(page, 'JobSettingsTab-speed-quality')
      await speedQualitySelect.selectOption('quality')
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
      const notesContainer = autoId(page, 'JobSettingsTab-internal-notes')
      const quillEditor = notesContainer.locator('.ql-editor')
      await quillEditor.waitFor({ timeout: 15000 })
      await quillEditor.click()
      await quillEditor.fill(newNotes)
      await page.click('body')
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify internal notes were saved', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').waitFor({ timeout: 30000 })
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-internal-notes').waitFor({ timeout: 10000 })

      const notesContainer = autoId(page, 'JobSettingsTab-internal-notes')
      const quillEditor = notesContainer.locator('.ql-editor')
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

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-pricing-method').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('change pricing method to Time & Materials', async () => {
      const pricingSelect = autoId(page, 'JobSettingsTab-pricing-method')
      await pricingSelect.selectOption('time_materials')
      await pricingSelect.blur()
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
      const pricingDisplay = autoId(page, 'JobView-pricing-method-display')
      await pricingDisplay.waitFor({ timeout: 10000 })
      await pricingDisplay.click()
    })

    await test.step('select Fixed Price from dropdown', async () => {
      const pricingSelect = autoId(page, 'JobView-pricing-method-select')
      await pricingSelect.waitFor({ timeout: 5000 })
      await pricingSelect.selectOption('fixed_price')

      const confirmBtn = autoId(page, 'JobView-pricing-method-confirm')
      await confirmBtn.click()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify pricing method was saved', async () => {
      await page.reload()

      const pricingDisplay = autoId(page, 'JobView-pricing-method-display')
      await expect(pricingDisplay).toContainText('Fixed Price', { timeout: 10000 })

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

      const confirmBtn = autoId(page, 'JobView-status-confirm')
      await confirmBtn.click()
    })

    await test.step('wait for autosave', async () => {
      await waitForAutosave(page)
    })

    await test.step('verify status was saved', async () => {
      await page.reload()

      const statusDisplay = autoId(page, 'JobView-status-display')
      await expect(statusDisplay).toContainText('In Progress', { timeout: 10000 })
    })
  })

  test('change person', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'PersonSelector-modal-button').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('open person selection modal', async () => {
      await autoId(page, 'PersonSelector-modal-button').click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })
    })

    await test.step('create a new person to switch to', async () => {
      const submitButton = autoId(page, 'PersonSelectionModal-submit')
      await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })

      const timestamp = Date.now()
      await autoId(page, 'PersonSelectionModal-name-input').fill(`New Person ${timestamp}`)
      await autoId(page, 'PersonSelectionModal-email-input').fill(
        `newperson${timestamp}@example.com`,
      )
      await submitButton.click()

      await autoId(page, 'PersonSelectionModal-container').waitFor({
        state: 'hidden',
        timeout: 10000,
      })
    })

    await test.step('verify person was updated', async () => {
      const personDisplay = autoId(page, 'PersonSelector-display')
      await expect(personDisplay).toHaveValue(/New Person/, { timeout: 10000 })
    })
  })

  test('edit an existing person from the selection modal', async ({ authenticatedPage: page }) => {
    // Dedicated job — this mutates the company's people list, so isolate it.
    const jobUrl = await createTestJob(page, 'Edit Person')
    await page.goto(jobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'PersonSelector-modal-button').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    const timestamp = Date.now()
    const originalName = `Edit Target ${timestamp}`
    const updatedName = `Edited Name ${timestamp}`

    await test.step('create a person to edit', async () => {
      await autoId(page, 'PersonSelector-modal-button').click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

      const submitButton = autoId(page, 'PersonSelectionModal-submit')
      await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })
      await autoId(page, 'PersonSelectionModal-name-input').fill(originalName)
      await autoId(page, 'PersonSelectionModal-email-input').fill(`edit${timestamp}@example.com`)
      await submitButton.click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({
        state: 'hidden',
        timeout: 10000,
      })
    })

    await test.step('reopen modal and enter edit mode', async () => {
      await autoId(page, 'PersonSelector-modal-button').click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

      const card = page
        .locator('[data-automation-id^="PersonSelectionModal-card-"]')
        .filter({ hasText: originalName })
        .first()
      await card.waitFor({ timeout: 10000 })
      await card.hover()
      await card.locator('[data-automation-id="PersonSelectionModal-edit-button"]').click()

      // Form flips to edit mode: submit label + prefilled name prove it.
      await expect(autoId(page, 'PersonSelectionModal-submit')).toHaveText('Update Person', {
        timeout: 10000,
      })
      await expect(autoId(page, 'PersonSelectionModal-name-input')).toHaveValue(originalName)
    })

    await test.step('change the name and save', async () => {
      const nameInput = autoId(page, 'PersonSelectionModal-name-input')
      await nameInput.clear()
      await nameInput.pressSequentially(updatedName, { delay: 10 })
      await autoId(page, 'PersonSelectionModal-submit').click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({
        state: 'hidden',
        timeout: 10000,
      })
    })

    await test.step('verify the edit persisted', async () => {
      // Selected person display reflects the new name.
      await expect(autoId(page, 'PersonSelector-display')).toHaveValue(new RegExp(updatedName), {
        timeout: 10000,
      })

      // And the list shows the renamed person, not the old name.
      await autoId(page, 'PersonSelector-modal-button').click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })
      await expect(
        page
          .locator('[data-automation-id^="PersonSelectionModal-card-"]')
          .filter({ hasText: updatedName }),
      ).toHaveCount(1, { timeout: 10000 })
      await expect(
        page
          .locator('[data-automation-id^="PersonSelectionModal-card-"]')
          .filter({ hasText: originalName }),
      ).toHaveCount(0)
    })
  })

  test('delete (archive) a person from the selection modal', async ({
    authenticatedPage: page,
  }) => {
    const jobUrl = await createTestJob(page, 'Delete Person')
    const jobId = getJobIdFromUrl(jobUrl)
    const headerUrl = `/api/job/jobs/${jobId}/header/`
    await page.goto(jobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'PersonSelector-modal-button').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    const timestamp = Date.now()
    const personName = `Delete Target ${timestamp}`

    await test.step('create a person to delete', async () => {
      await autoId(page, 'PersonSelector-modal-button').click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

      const submitButton = autoId(page, 'PersonSelectionModal-submit')
      await expect(submitButton).toHaveText('Create Person', { timeout: 10000 })
      await autoId(page, 'PersonSelectionModal-name-input').fill(personName)
      await autoId(page, 'PersonSelectionModal-email-input').fill(`delete${timestamp}@example.com`)
      await submitButton.click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({
        state: 'hidden',
        timeout: 10000,
      })
    })

    // A previous direct person-save path advanced Job.updated_at without refreshing
    // the browser's OCC token. Waiting for authoritative selection here makes the
    // subsequent archive exercise the real select-then-clear regression.
    await expect
      .poll(
        async () => {
          const response = await page.request.get(headerUrl)
          if (!response.ok()) {
            throw new Error(`Job header read failed: ${response.status()} ${await response.text()}`)
          }
          return parseJobHeader(await response.json()).person_name
        },
        { timeout: 10000 },
      )
      .toBe(personName)

    await test.step('reopen modal and delete the person', async () => {
      await autoId(page, 'PersonSelector-modal-button').click()
      await autoId(page, 'PersonSelectionModal-container').waitFor({ timeout: 10000 })

      const card = page
        .locator('[data-automation-id^="PersonSelectionModal-card-"]')
        .filter({ hasText: personName })
        .first()
      await card.waitFor({ timeout: 10000 })
      await card.hover()
      await card.locator('[data-automation-id="PersonSelectionModal-delete-button"]').click()

      // Confirmation overlay, then confirm.
      await expect(page.getByText('Delete Person?')).toBeVisible({ timeout: 10000 })
      await autoId(page, 'PersonSelectionModal-confirm-delete').click()
    })

    await test.step('verify the person is removed from the list', async () => {
      // Modal stays open; the archived person drops out of the company's list.
      await expect(
        page
          .locator('[data-automation-id^="PersonSelectionModal-card-"]')
          .filter({ hasText: personName }),
      ).toHaveCount(0, { timeout: 10000 })
    })

    await test.step('verify the archived person is cleared from the job', async () => {
      await expect
        .poll(
          async () => {
            const response = await page.request.get(headerUrl)
            if (!response.ok()) {
              throw new Error(
                `Job header read failed: ${response.status()} ${await response.text()}`,
              )
            }
            return parseJobHeader(await response.json()).person_id
          },
          { timeout: 10000 },
        )
        .toBeNull()

      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'PersonSelector-display').waitFor({ timeout: 10000 })
      await waitForSettingsInitialized(page)
      await page.waitForLoadState('networkidle')
      await expect(autoId(page, 'PersonSelector-display')).toHaveValue('')
    })
  })

  test('change company', async ({ authenticatedPage: page }) => {
    // Create a dedicated job for this test — changing company mutates state
    // that would break other tests sharing sharedEditJobUrl
    const jobUrl = await createTestJob(page, 'Change Company')
    await page.goto(jobUrl)
    await page.waitForLoadState('networkidle')

    const companyDefaults = await getCompanyDefaults(page)
    const shopCompanyId = companyDefaults.shop_company
    if (typeof shopCompanyId !== 'string' || shopCompanyId === '') {
      throw new Error(`Company defaults carry no shop_company: ${JSON.stringify(shopCompanyId)}`)
    }
    const companiesResponse = await page.request.get('/api/companies/all/', {
      headers: { Accept: 'application/json' },
    })
    const companiesPayload: unknown = await companiesResponse.json()
    if (!Array.isArray(companiesPayload)) {
      throw new Error('Companies list response was not an array')
    }
    const shopCompany = companiesPayload
      .filter(isRecord)
      .find((company) => company.id === shopCompanyId)
    const shopCompanyName = shopCompany?.name
    if (typeof shopCompanyName !== 'string' || shopCompanyName === '') {
      throw new Error(`Shop company ${shopCompanyId} not found in the companies list`)
    }
    log(`Using shop company name: ${shopCompanyName}`)

    await autoId(page, 'JobViewTabs-jobSettings').click()
    await autoId(page, 'JobSettingsTab-change-company-btn').waitFor({ timeout: 10000 })
    await waitForSettingsInitialized(page)

    await test.step('click Change Company button', async () => {
      await autoId(page, 'JobSettingsTab-change-company-btn').click()
      await autoId(page, 'JobSettingsTab-company-change-panel').waitFor({ timeout: 5000 })
    })

    await test.step('search for and select a different company', async () => {
      const companyChangePanel = autoId(page, 'JobSettingsTab-company-change-panel')
      const companyInput = companyChangePanel.locator('input[type="text"]')

      // Search using first word of shop company name
      await companyInput.fill(shopCompanyName.split(' ')[0] ?? shopCompanyName)
      await page.waitForTimeout(1000) // Allow debounce

      const companyOption = page.getByRole('option', { name: shopCompanyName, exact: true })
      await companyOption.waitFor({ timeout: 10000 })
      await companyOption.click()
    })

    await test.step('confirm the company change', async () => {
      await autoId(page, 'JobSettingsTab-confirm-company-btn').click()
      await waitForAutosave(page)
    })

    await test.step('verify company was changed', async () => {
      const companyNameInput = autoId(page, 'JobSettingsTab-company-name')
      await expect(companyNameInput).toHaveValue(shopCompanyName)
    })

    await test.step('verify change persists after refresh', async () => {
      await page.reload()
      await autoId(page, 'JobViewTabs-jobSettings').click()
      await autoId(page, 'JobSettingsTab-company-name').waitFor({ timeout: 10000 })

      const companyNameInput = autoId(page, 'JobSettingsTab-company-name')
      await expect(companyNameInput).toHaveValue(shopCompanyName)
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

    const valuesBefore = await test.step('capture values before reload', async () => {
      return {
        jobName: await autoId(page, 'JobSettingsTab-job-name').inputValue(),
        description: await autoId(page, 'JobSettingsTab-description').inputValue(),
        orderNumber: await autoId(page, 'JobSettingsTab-order-number').inputValue(),
        pricingMethod: await autoId(page, 'JobSettingsTab-pricing-method').inputValue(),
        speedQuality: await autoId(page, 'JobSettingsTab-speed-quality').inputValue(),
        companyName: await autoId(page, 'JobSettingsTab-company-name').inputValue(),
      }
    })

    log('Values before reload:', valuesBefore)

    for (let i = 1; i <= 3; i++) {
      await test.step(`reload #${i} and verify values unchanged`, async () => {
        await page.reload()
        await autoId(page, 'JobViewTabs-jobSettings').click()
        await autoId(page, 'JobSettingsTab-job-name').waitFor({ timeout: 10000 })
        await waitForSettingsInitialized(page)

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
        await expect(autoId(page, 'JobSettingsTab-company-name')).toHaveValue(
          valuesBefore.companyName,
        )
      })
    }
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

      const options = payItemSelect.locator('option')
      const optionCount = await options.count()
      expect(optionCount).toBeGreaterThan(1) // More than just the placeholder
    })

    await test.step('select a different pay item', async () => {
      const payItemSelect = autoId(page, 'JobSettingsTab-default-pay-item')

      // Find and select a non-empty option (not the placeholder)
      const options = payItemSelect.locator('option')
      const optionCount = await options.count()

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
