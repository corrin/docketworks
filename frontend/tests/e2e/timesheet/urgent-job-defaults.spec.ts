import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId, getPhantomRowIndex, TEST_COMPANY_NAME } from '../helpers'
import { isRecord } from '../fixtures/api'
import { bookingDay, enterHours, isEntryWrite, openEntryViaDaily } from './support'

/**
 * Urgent-job billing defaults: picking an urgent job leaves the WAGE at
 * ordinary and raises the customer charge to 1.5x, visible in the grid and
 * exact on the create wire (request AND response meta).
 */

async function getCompanyId(page: Page): Promise<string> {
  const response = await page.request.get('/api/companies/all/', {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok()) {
    throw new Error(`companies/all failed: ${response.status()} ${await response.text()}`)
  }
  const payload: unknown = await response.json()
  const companies = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.companies)
      ? payload.companies
      : null
  if (!companies)
    throw new Error(`Unexpected companies/all shape: ${JSON.stringify(payload).slice(0, 300)}`)
  const company = companies.find(
    (candidate: unknown) => isRecord(candidate) && candidate.name === TEST_COMPANY_NAME,
  )
  if (!isRecord(company) || typeof company.id !== 'string') {
    throw new Error(`Test company "${TEST_COMPANY_NAME}" not found in companies/all`)
  }
  return company.id
}

async function createUrgentJob(page: Page): Promise<{ jobId: string; jobNumber: number }> {
  const companyId = await getCompanyId(page)
  const response = await page.request.post('/api/job/jobs/', {
    data: {
      name: `[TEST] Urgent Job ${Date.now()}`,
      company_id: companyId,
      description: '',
      order_number: '',
      notes: '',
      person_id: null,
      estimated_materials: 0,
      estimated_time: 0,
      is_urgent: true,
      pricing_methodology: 'time_materials',
    },
  })
  if (!response.ok()) {
    throw new Error(`Urgent job create failed: ${response.status()} ${await response.text()}`)
  }
  const body: unknown = await response.json()
  if (!isRecord(body) || typeof body.job_id !== 'string' || typeof body.job_number !== 'number') {
    throw new Error(`Unexpected job create response: ${JSON.stringify(body).slice(0, 300)}`)
  }
  return { jobId: body.job_id, jobNumber: body.job_number }
}

test.describe('urgent job timesheet defaults', () => {
  test('an urgent job defaults ordinary wage and 1.5x bill, on screen and on the wire', async ({
    authenticatedPage: page,
  }) => {
    const { jobId, jobNumber } = await createUrgentJob(page)
    const date = bookingDay('urgentJobDefaults')

    await openEntryViaDaily(page, date)
    const rowIndex = await getPhantomRowIndex(page)

    await autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`).click()
    const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-search`)
    await expect(search).toBeFocused()
    await search.fill(String(jobNumber))
    const option = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-option-${jobNumber}`)
    await option.waitFor({ timeout: 10000 })
    // The option row itself flags urgency before selection.
    await expect(option.locator('span', { hasText: 'URGENT' })).toBeVisible()
    await option.click()

    const trigger = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`)
    await expect(trigger.locator('span', { hasText: '!' })).toBeVisible({ timeout: 5000 })
    await expect(autoId(page, `SmartTimesheetTable-urgentBadge-${rowIndex}`)).toContainText(
      'Urgent',
    )
    await expect(autoId(page, `SmartTimesheetTable-rate-${rowIndex}`)).toContainText('Ord')
    await expect(autoId(page, `SmartTimesheetTable-billRate-${rowIndex}`)).toContainText('1.5x')

    const createPost = page.waitForResponse((response) => isEntryWrite(response, 'POST'), {
      timeout: 30000,
    })
    await enterHours(page, rowIndex, '2')
    const response = await createPost
    expect(response.ok(), await response.text()).toBe(true)

    const requestBody: unknown = response.request().postDataJSON()
    if (!isRecord(requestBody)) {
      throw new Error(`Create request was not an entry: ${JSON.stringify(requestBody)}`)
    }
    expect(requestBody.job_id).toBe(jobId)
    expect(requestBody.wage_rate_multiplier).toBe(1.0)
    // The grid shows the 1.5 but leaves it to the server: one copy of the rule.
    expect(requestBody).not.toHaveProperty('bill_rate_multiplier')
    expect(requestBody.is_billable).toBe(true)

    const responseBody: unknown = await response.json()
    if (!isRecord(responseBody)) {
      throw new Error(`Create response was not an entry: ${JSON.stringify(responseBody)}`)
    }
    expect(responseBody.wage_rate_multiplier).toBe(1.0)
    expect(responseBody.bill_rate_multiplier).toBe(1.5)
  })
})
