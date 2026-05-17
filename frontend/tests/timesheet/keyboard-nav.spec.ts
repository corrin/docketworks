import { test, expect } from '../fixtures/auth'
import type { Response } from '@playwright/test'
import { getTimesheetJobs, getTimesheetStaff } from '../fixtures/api'
import { autoId, createTestJob, getPhantomRowIndex } from '../fixtures/helpers'
import { getLatestWeekdayDate } from '../../src/utils/dateUtils'

type CreatedCostLineResponse = Record<string, unknown>

async function expectCreatedCostLine(
  response: Response,
  expected: {
    entrySeq: number
    description: string
    hours: number
    totalCost: number
    totalRevenue: number
    staffId: string
  },
): Promise<void> {
  const body = (await response.json()) as CreatedCostLineResponse
  expect(body.entry_seq).toBe(expected.entrySeq)
  expect(body.desc).toBe(expected.description)
  expect(Number(body.quantity)).toBeCloseTo(expected.hours, 2)
  expect(Number(body.total_cost)).toBeCloseTo(expected.totalCost, 1)
  expect(Number(body.total_rev)).toBeCloseTo(expected.totalRevenue, 1)

  const meta = body.meta
  expect(meta).toEqual(expect.objectContaining({ staff_id: expected.staffId }))
}

test.describe('keyboard Tab entry flow', () => {
  let staffId: string
  let staffWageRate: number
  let job1ChargeOutRate: number
  let job2ChargeOutRate: number
  let jobNumber1: string
  let jobNumber2: string

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

    const date = getLatestWeekdayDate()
    const timesheetStaff = await getTimesheetStaff(page, date)
    expect(timesheetStaff.length).toBeGreaterThan(0)
    staffId = timesheetStaff[0].id
    staffWageRate = timesheetStaff[0].wageRate ?? 30

    const url1 = await createTestJob(page, 'KbdNav-1')
    await page.goto(url1.split('?')[0])
    await page.waitForLoadState('networkidle')
    const t1 = await autoId(page, 'JobView-job-number').first().innerText()
    jobNumber1 = t1.match(/#(\d+)/)?.[1] ?? ''

    const url2 = await createTestJob(page, 'KbdNav-2')
    await page.goto(url2.split('?')[0])
    await page.waitForLoadState('networkidle')
    const t2 = await autoId(page, 'JobView-job-number').first().innerText()
    jobNumber2 = t2.match(/#(\d+)/)?.[1] ?? ''

    expect(jobNumber1).toBeTruthy()
    expect(jobNumber2).toBeTruthy()

    const jobs = await getTimesheetJobs(page)
    const timesheetJob1 = jobs.find((job) => String(job.job_number) === jobNumber1)
    const timesheetJob2 = jobs.find((job) => String(job.job_number) === jobNumber2)
    expect(timesheetJob1).toBeTruthy()
    expect(timesheetJob2).toBeTruthy()
    job1ChargeOutRate = timesheetJob1!.charge_out_rate
    job2ChargeOutRate = timesheetJob2!.charge_out_rate

    await context.close()
  })

  test('keyboard-only job, tab, hours, tab, description, tab — two rows with verified data', async ({
    authenticatedPage: page,
  }) => {
    let delayedFirstCreate = false
    await page.route(/\/cost_lines\/?/, async (route) => {
      if (route.request().method() === 'POST' && !delayedFirstCreate) {
        delayedFirstCreate = true
        await page.waitForTimeout(700)
      }
      await route.continue()
    })

    await page.goto(`/timesheets/entry?date=${getLatestWeekdayDate()}&staffId=${staffId}`)
    await page.waitForLoadState('networkidle')

    const r0 = await getPhantomRowIndex(page)
    const firstSeq = r0 + 1
    const secondSeq = firstSeq + 1

    const assertRow = async (
      seq: number,
      jobNum: string,
      hoursText: string,
      desc: string,
      hrs: number,
    ) => {
      const row = page.locator(`tr:has([data-entry-seq="${seq}"])`)

      await expect(row.locator(`[data-automation-id$="-trigger"]`)).toHaveText(
        new RegExp(`#${jobNum}`),
      )
      await expect(row.locator(`[data-automation-id^="SmartTimesheetTable-hours-"]`)).toHaveValue(
        hoursText,
      )
      await expect(
        row.locator(`[data-automation-id^="SmartTimesheetTable-description-"]`),
      ).toHaveValue(desc)

      const wageText = await row
        .locator(`[data-automation-id^="SmartTimesheetTable-wage-"]`)
        .textContent()
      const billText = await row
        .locator(`[data-automation-id^="SmartTimesheetTable-bill-"]`)
        .textContent()
      const wageVal = parseFloat(
        (wageText?.match(/\$?([\d,]+\.?\d*)/) ?? ['0'])[1].replace(/,/g, ''),
      )
      const billVal = parseFloat(
        (billText?.match(/\$?([\d,]+\.?\d*)/) ?? ['0'])[1].replace(/,/g, ''),
      )

      expect(wageVal).toBeCloseTo(hrs * staffWageRate, 1)
      const expectedRate = jobNum === jobNumber1 ? job1ChargeOutRate : job2ChargeOutRate
      expect(billVal).toBeCloseTo(hrs * expectedRate, 1)
    }

    // One mouse action is allowed to place the cursor in the first blank row.
    // From here until both rows are saved, this workflow must be keyboard-only.
    await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-trigger`).click()
    await expect(autoId(page, `SmartTimesheetTable-jobPicker-${r0}-search`)).toBeFocused({
      timeout: 3000,
    })
    await page.keyboard.type(jobNumber1)
    await expect(
      autoId(page, `SmartTimesheetTable-jobPicker-${r0}-option-${jobNumber1}`),
    ).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-hours-${r0}`)).toBeFocused({ timeout: 3000 })

    await page.keyboard.type('2')
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-description-${r0}`)).toBeFocused({
      timeout: 3000,
    })

    await page.keyboard.type('Cutting')
    const row1Post = page.waitForResponse(
      (res: Response) => res.url().includes('/cost_lines/') && res.request().method() === 'POST',
      { timeout: 15000 },
    )
    await page.keyboard.press('Tab')

    const blockedPhantom = autoId(page, `SmartTimesheetTable-jobPicker-${r0 + 1}-trigger`)
    await blockedPhantom.waitFor({ timeout: 3000 })
    await expect(blockedPhantom).toBeDisabled({ timeout: 3000 })

    const row1Response = await row1Post
    await expectCreatedCostLine(row1Response, {
      entrySeq: firstSeq,
      description: 'Cutting',
      hours: 2,
      totalCost: 2 * staffWageRate,
      totalRevenue: 2 * job1ChargeOutRate,
      staffId,
    })

    const r1 = r0 + 1
    const row2Trigger = autoId(page, `SmartTimesheetTable-jobPicker-${r1}-trigger`)
    await expect(row2Trigger).toBeEnabled({ timeout: 5000 })
    await expect(autoId(page, `SmartTimesheetTable-jobPicker-${r1}-search`)).toBeFocused({
      timeout: 5000,
    })

    await test.step('row 1 rendered from backend response', () =>
      assertRow(firstSeq, jobNumber1, '2h', 'Cutting', 2))

    // Row 2 continues from the automatic focus handoff, still keyboard only.
    await page.keyboard.type(jobNumber2)
    await expect(
      autoId(page, `SmartTimesheetTable-jobPicker-${r1}-option-${jobNumber2}`),
    ).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-hours-${r1}`)).toBeFocused({ timeout: 3000 })

    await page.keyboard.type('3.5')
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-description-${r1}`)).toBeFocused({
      timeout: 3000,
    })

    await page.keyboard.type('Welding')
    const row2Post = page.waitForResponse(
      (res: Response) => res.url().includes('/cost_lines/') && res.request().method() === 'POST',
      { timeout: 15000 },
    )
    await page.keyboard.press('Tab')
    const row2Response = await row2Post
    await expectCreatedCostLine(row2Response, {
      entrySeq: secondSeq,
      description: 'Welding',
      hours: 3.5,
      totalCost: 3.5 * staffWageRate,
      totalRevenue: 3.5 * job2ChargeOutRate,
      staffId,
    })

    await page.waitForLoadState('networkidle')

    await test.step('row 1 data', () => assertRow(firstSeq, jobNumber1, '2h', 'Cutting', 2))
    await test.step('row 2 data', () => assertRow(secondSeq, jobNumber2, '3h 30m', 'Welding', 3.5))
  })
})
