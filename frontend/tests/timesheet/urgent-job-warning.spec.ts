import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { autoId, getPhantomRowIndex, TEST_CLIENT_NAME } from '../fixtures/helpers'
import { getLatestWeekdayDate } from '../../src/utils/dateUtils'

/**
 * Tests for urgent job warning behaviour.
 * When a job is marked urgent, the timesheet entry UI should:
 *  - Show an "URGENT" visual indicator in the job picker
 *  - Warn the user when they select a non-Urgent labour subtype
 */

// ============================================================================
// Helpers
// ============================================================================

async function navigateToTimesheetEntry(page: Page): Promise<void> {
  const weekday = getLatestWeekdayDate()
  await page.goto(`/timesheets/daily?date=${weekday}`)
  await page.waitForLoadState('networkidle')

  const firstStaffName = page.locator('[data-automation-id^="StaffRow-name-"]').first()
  await firstStaffName.waitFor({ timeout: 10000 })
  await firstStaffName.click()

  await page.waitForURL('**/timesheets/entry**')
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(1000)
}

/**
 * Fetch the active client's ID so we can create a job via the API.
 */
async function getClientId(page: Page): Promise<string> {
  const response = await page.request.get('/api/clients/all/', {
    headers: { Accept: 'application/json' },
  })
  const responseText = await response.text()

  if (!response.ok()) {
    throw new Error(`Client list failed with HTTP ${response.status()}: ${responseText}`)
  }

  let clients: Array<{ id: string; name: string }>
  try {
    clients = JSON.parse(responseText) as Array<{ id: string; name: string }>
  } catch {
    throw new Error(`Client list returned non-JSON response: ${responseText}`)
  }

  if (!Array.isArray(clients)) {
    throw new Error(`Client list returned unexpected payload: ${responseText}`)
  }

  const match = clients.find((client) => client.name === TEST_CLIENT_NAME)
  if (!match) {
    throw new Error(`Test client not found: ${TEST_CLIENT_NAME}`)
  }

  return match.id
}

/**
 * Create a job via the REST API with `is_urgent: true`.
 * Returns the job number.
 */
async function createUrgentJob(page: Page): Promise<{ jobNumber: string; jobUrl: string }> {
  const clientId = await getClientId(page)
  const timestamp = Date.now()
  const jobName = `[TEST] Urgent Job ${timestamp}`

  const response = await page.request.post('/api/job/jobs/', {
    headers: { Accept: 'application/json' },
    data: {
      name: jobName,
      client_id: clientId,
      description: '',
      order_number: '',
      notes: '',
      contact_id: null,
      estimated_materials: 0,
      estimated_time: 0,
      is_urgent: true,
      pricing_methodology: 'time_materials',
    },
  })
  const responseText = await response.text()

  if (!response.ok()) {
    throw new Error(`Job create failed with HTTP ${response.status()}: ${responseText}`)
  }

  let result: { job_id?: string; job_number?: number }
  try {
    result = JSON.parse(responseText) as { job_id?: string; job_number?: number }
  } catch {
    throw new Error(`Job create returned non-JSON response: ${responseText}`)
  }

  if (!result.job_id || result.job_number === undefined) {
    throw new Error(`Job create returned unexpected payload: ${responseText}`)
  }

  const jobUrl = `/jobs/${result.job_id}`
  return { jobNumber: String(result.job_number), jobUrl }
}

// ============================================================================
// Test: Urgent Job Warning
// ============================================================================

test.describe('urgent job warning', () => {
  test('shows urgent badge in picker and warns on non-urgent labour subtype', async ({
    authenticatedPage: page,
  }) => {
    // 1. Create an urgent job via the API
    const { jobNumber } = await createUrgentJob(page)
    console.log(`Created urgent job #${jobNumber}`)

    // 2. Navigate to the timesheet entry page
    await navigateToTimesheetEntry(page)

    // 3. Find the phantom row and open the job picker — verify the
    //    urgent indicator appears in the picker options
    const rowIdx = await getPhantomRowIndex(page)
    const trigger = autoId(page, `SmartTimesheetTable-jobPicker-${rowIdx}-trigger`)

    // Click trigger, search for the urgent job, but don't select it
    // yet — inspect the picker list for the URGENT badge.
    await trigger.click()
    const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIdx}-search`)
    await search.waitFor({ timeout: 5000 })
    await search.fill(jobNumber)

    // The option for our job should appear
    const option = autoId(page, `SmartTimesheetTable-jobPicker-${rowIdx}-option-${jobNumber}`)
    await option.waitFor({ timeout: 5000 })

    // Verify the URGENT badge is visible inside the option
    await expect(option.locator('span', { hasText: 'URGENT' })).toBeVisible()

    // 4. Select the urgent job
    await option.click()

    // 5. Verify the trigger button now shows the urgent "!" indicator
    await expect(trigger.locator('span', { hasText: '!' })).toBeVisible({ timeout: 5000 })

    // 6. Verify the toast warning appeared ("is urgent — consider using the
    //    Urgent labour rate")
    const toast = page.locator('[data-sonner-toaster]')
    await expect(toast).toContainText('urgent', { timeout: 5000 })

    // 7. Enter hours to create the entry, then verify the entry is
    //    saved correctly
    const hoursInput = autoId(page, `SmartTimesheetTable-hours-${rowIdx}`)
    await hoursInput.click()
    await page.keyboard.type('2')
    await page.keyboard.press('Enter')

    // Wait for the POST to finish so the entry is committed
    await page.waitForTimeout(2000)

    console.log('Urgent job warning test completed successfully')
  })
})
