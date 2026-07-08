import { test, expect } from '../fixtures/auth'
import type { Page, Response } from '@playwright/test'
import { autoId, getPhantomRowIndex, TEST_COMPANY_NAME } from '../fixtures/helpers'
import { getLatestWeekdayDate } from '../../src/utils/dateUtils'

type JsonObject = Record<string, unknown>

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function numberField(value: unknown, fieldName: string): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  throw new Error(`Expected numeric ${fieldName}, got ${JSON.stringify(value)}`)
}

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

async function getCompanyId(page: Page): Promise<string> {
  const response = await page.request.get('/api/companies/all/', {
    headers: { Accept: 'application/json' },
  })
  const responseText = await response.text()

  if (!response.ok()) {
    throw new Error(`Company list failed with HTTP ${response.status()}: ${responseText}`)
  }

  let companies: Array<{ id: string; name: string }>
  try {
    companies = JSON.parse(responseText) as Array<{ id: string; name: string }>
  } catch {
    throw new Error(`Company list returned non-JSON response: ${responseText}`)
  }

  if (!Array.isArray(companies)) {
    throw new Error(`Company list returned unexpected payload: ${responseText}`)
  }

  const match = companies.find((company) => company.name === TEST_COMPANY_NAME)
  if (!match) {
    throw new Error(`Test company not found: ${TEST_COMPANY_NAME}`)
  }

  return match.id
}

async function createUrgentJob(page: Page): Promise<{ jobId: string; jobNumber: string }> {
  const companyId = await getCompanyId(page)
  const timestamp = Date.now()
  const jobName = `[TEST] Urgent Job ${timestamp}`

  const response = await page.request.post('/api/job/jobs/', {
    headers: { Accept: 'application/json' },
    data: {
      name: jobName,
      company_id: companyId,
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

  return {
    jobId: result.job_id,
    jobNumber: String(result.job_number),
  }
}

function isCostLineCreateResponse(response: Response, jobId: string): boolean {
  const url = new URL(response.url())
  return (
    url.pathname === `/api/job/jobs/${jobId}/cost_sets/actual/cost_lines/` &&
    response.request().method() === 'POST'
  )
}

test.describe('urgent job timesheet defaults', () => {
  test('marks urgent jobs and saves a 1.5x customer charge with ordinary wage', async ({
    authenticatedPage: page,
  }) => {
    const { jobId, jobNumber } = await createUrgentJob(page)

    await navigateToTimesheetEntry(page)

    const rowIdx = await getPhantomRowIndex(page)
    const trigger = autoId(page, `SmartTimesheetTable-jobPicker-${rowIdx}-trigger`)

    await trigger.click()
    const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIdx}-search`)
    await search.waitFor({ timeout: 5000 })
    await search.fill(jobNumber)

    const option = autoId(page, `SmartTimesheetTable-jobPicker-${rowIdx}-option-${jobNumber}`)
    await option.waitFor({ timeout: 5000 })
    await expect(option.locator('span', { hasText: 'URGENT' })).toBeVisible()

    await option.click()

    await expect(trigger.locator('span', { hasText: '!' })).toBeVisible({ timeout: 5000 })
    await expect(autoId(page, `SmartTimesheetTable-urgentBadge-${rowIdx}`)).toContainText('Urgent')
    await expect(autoId(page, `SmartTimesheetTable-rate-${rowIdx}`)).toContainText('Ord')
    await expect(autoId(page, `SmartTimesheetTable-billRate-${rowIdx}`)).toContainText('1.5x')

    const hoursInput = autoId(page, `SmartTimesheetTable-hours-${rowIdx}`)
    const createResponsePromise = page.waitForResponse(
      (response) => isCostLineCreateResponse(response, jobId),
      { timeout: 30000 },
    )

    await hoursInput.click()
    await page.keyboard.type('2')
    await page.keyboard.press('Enter')

    const createResponse = await createResponsePromise
    const responseText = await createResponse.text()
    expect(createResponse.ok(), responseText).toBe(true)

    const requestPayload = createResponse.request().postDataJSON() as unknown
    if (!isJsonObject(requestPayload) || !isJsonObject(requestPayload.meta)) {
      throw new Error(`Cost line create sent unexpected payload: ${JSON.stringify(requestPayload)}`)
    }
    expect(numberField(requestPayload.meta.wage_rate_multiplier, 'wage_rate_multiplier')).toBe(1.0)
    expect(numberField(requestPayload.meta.bill_rate_multiplier, 'bill_rate_multiplier')).toBe(1.5)
    expect(requestPayload.meta.is_billable).toBe(true)

    const responsePayload = JSON.parse(responseText) as unknown
    if (isJsonObject(responsePayload) && isJsonObject(responsePayload.meta)) {
      expect(
        numberField(responsePayload.meta.wage_rate_multiplier, 'response wage multiplier'),
      ).toBe(1.0)
      expect(
        numberField(responsePayload.meta.bill_rate_multiplier, 'response bill multiplier'),
      ).toBe(1.5)
    }
  })
})
