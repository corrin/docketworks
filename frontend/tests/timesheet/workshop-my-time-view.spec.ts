import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { autoId, createTestJob } from '../fixtures/helpers'

/**
 * Integration tests for WorkshopMyTimeView.
 * Covers day navigation, refresh, add/update/delete entry flows.
 */

// ============================================================================
// Helper Functions
// ============================================================================

async function loginAndCreateJob(page: Page): Promise<{ jobUrl: string; jobNumber: string }> {
  const username = process.env.E2E_TEST_USERNAME
  const password = process.env.E2E_TEST_PASSWORD

  if (!username || !password) {
    throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env or .env.test')
  }

  await page.goto('/login')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await page.waitForURL('**/kanban')

  const jobUrl = await createTestJob(page, 'Workshop My Time')

  await page.goto(jobUrl.split('?')[0])
  await page.waitForLoadState('networkidle')

  const jobNumberElement = autoId(page, 'JobView-job-number').first()
  await jobNumberElement.waitFor({ timeout: 10000 })
  const jobNumberText = await jobNumberElement.innerText()
  const match = jobNumberText.match(/#(\d+)/)
  const jobNumber = match ? match[1] : ''

  if (!jobNumber) {
    throw new Error(`Failed to extract job number from: "${jobNumberText}"`)
  }

  return { jobUrl, jobNumber }
}

async function openMyTimeView(page: Page): Promise<void> {
  await page.goto('/timesheets/my-time')
  await page.waitForLoadState('networkidle')
  await expect(page.getByText('Workshop timesheets')).toBeVisible({ timeout: 10000 })
}

async function getHeaderDateLabel(page: Page): Promise<string> {
  const badge = autoId(page, 'WorkshopMyTimeHeader-date')
  await badge.waitFor({ timeout: 10000 })
  return (await badge.textContent())?.trim() || ''
}

async function selectJobInPicker(page: Page, jobNumber: string): Promise<void> {
  await autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker').click()
  await expect(page.getByRole('heading', { name: 'Select a job' })).toBeVisible({
    timeout: 10000,
  })

  const searchInput = autoId(page, 'WorkshopJobPickerDrawer-search')
  await expect(searchInput).toBeVisible({ timeout: 10000 })
  await searchInput.fill(jobNumber)

  const jobRow = page
    .locator('tbody tr')
    .filter({ hasText: `#${jobNumber}` })
    .first()
  await jobRow.waitFor({ timeout: 10000 })
  await jobRow.getByRole('button', { name: 'Select' }).click()

  await expect(page.getByRole('heading', { name: 'Select a job' })).toBeHidden({
    timeout: 10000,
  })
}

async function waitForTimesheetResponse(
  page: Page,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
): Promise<void> {
  await page.waitForResponse(
    (response) =>
      response.url().includes('/job/api/workshop/timesheets/') &&
      response.request().method() === method &&
      (response.status() === 200 || response.status() === 201 || response.status() === 204),
    { timeout: 15000 },
  )
}

async function getCalendarEventIds(page: Page): Promise<Set<string>> {
  const events = page.locator('[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id]')
  const ids = await events.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute('data-event-id') || '').filter(Boolean),
  )
  return new Set(ids)
}

async function waitForNewCalendarEvent(
  page: Page,
  knownIds: Set<string>,
  jobNumber: string,
  timeoutMs = 15000,
): Promise<string> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const events = page.locator('[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id]')
    const handles = await events.elementHandles()
    for (const handle of handles) {
      const id = await handle.getAttribute('data-event-id')
      if (!id || knownIds.has(id)) continue
      const text = (await handle.innerText()) || ''
      if (text.includes(`#${jobNumber}`)) {
        return id
      }
    }
    await page.waitForTimeout(300)
  }
  throw new Error('Timed out waiting for new calendar event.')
}

// ============================================================================
// Test Suite: Workshop My Time View
// ============================================================================

test.describe.serial('workshop my time view', () => {
  let jobNumber: string

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()

    const jobResult = await loginAndCreateJob(page)
    jobNumber = jobResult.jobNumber
    console.log(`Created job for Workshop My Time tests: #${jobNumber}`)

    await context.close()
  })

  test('moves between days', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)

    const initialDate = await getHeaderDateLabel(page)

    await test.step('move to previous day', async () => {
      await autoId(page, 'WorkshopMyTimeHeader-previous-day').click()
      await expect(autoId(page, 'WorkshopMyTimeHeader-date')).not.toHaveText(initialDate)
    })

    await test.step('move to next day', async () => {
      await autoId(page, 'WorkshopMyTimeHeader-next-day').click()
      await expect(autoId(page, 'WorkshopMyTimeHeader-date')).toHaveText(initialDate)
    })
  })

  test('refreshes a day', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)

    await test.step('refresh current day data', async () => {
      const refreshPromise = waitForTimesheetResponse(page, 'GET')
      await Promise.all([
        refreshPromise,
        autoId(page, 'WorkshopTimesheetSummaryCard-refresh').click(),
      ])
    })
  })

  test('adds, updates, and deletes an entry', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)

    let entryId = ''

    await test.step('add a new entry via the drawer', async () => {
      const existingEventIds = await getCalendarEventIds(page)

      await autoId(page, 'WorkshopTimesheetSummaryCard-add').click()
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible({
        timeout: 10000,
      })

      await selectJobInPicker(page, jobNumber)
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker')).toContainText(
        `#${jobNumber}`,
      )

      await autoId(page, 'WorkshopTimesheetEntryDrawer-start-time').fill('08:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-end-time').fill('09:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-description').fill('Workshop test entry')

      const submitButton = autoId(page, 'WorkshopTimesheetEntryDrawer-submit')
      await expect(submitButton).toBeEnabled({ timeout: 10000 })
      const createResponsePromise = page.waitForResponse(
        (response) =>
          response.url().includes('/job/api/workshop/timesheets/') &&
          response.request().method() === 'POST' &&
          (response.status() === 200 || response.status() === 201),
        { timeout: 15000 },
      )

      await submitButton.click({ force: true })

      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeHidden({
        timeout: 10000,
      })

      const createResponse = await createResponsePromise
      const responseBody = await createResponse.json()
      entryId = String(responseBody.id || '')
      if (!entryId) {
        throw new Error('Failed to capture entry id from create response.')
      }

      const calendarEntryId = await waitForNewCalendarEvent(page, existingEventIds, jobNumber)
      if (calendarEntryId !== entryId) {
        console.warn(`Calendar entry ID mismatch: response=${entryId}, calendar=${calendarEntryId}`)
      }

      const eventLocator = page.locator(
        `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`,
      )
      await expect(eventLocator).toBeVisible({ timeout: 15000 })
      await expect(eventLocator).toContainText(`#${jobNumber}`)
    })

    await test.step('update the entry', async () => {
      const eventLocator = page.locator(
        `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`,
      )
      await eventLocator.click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })

      await autoId(page, 'WorkshopTimesheetEntryDrawer-end-time').fill('10:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-description').fill(
        'Workshop test entry updated',
      )

      const updatePromise = waitForTimesheetResponse(page, 'PATCH')
      await Promise.all([
        updatePromise,
        autoId(page, 'WorkshopTimesheetEntryDrawer-submit').click(),
      ])

      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })

      await eventLocator.click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-description')).toHaveValue(
        'Workshop test entry updated',
      )
      await autoId(page, 'WorkshopTimesheetEntryDrawer-cancel').click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })
    })

    await test.step('delete the entry', async () => {
      const eventLocator = page.locator(
        `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`,
      )
      await eventLocator.click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })

      const deletePromise = waitForTimesheetResponse(page, 'DELETE')
      await Promise.all([
        deletePromise,
        autoId(page, 'WorkshopTimesheetEntryDrawer-delete').click(),
      ])

      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })
      await expect(
        page.locator(
          `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`,
        ),
      ).toHaveCount(0)
    })
  })
})
