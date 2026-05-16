import { test, expect } from '../fixtures/auth'
import type { Response } from '@playwright/test'
import { getCompanyDefaults, getTimesheetStaff } from '../fixtures/api'
import { autoId, createTestJob, getPhantomRowIndex } from '../fixtures/helpers'
import { getLatestWeekdayDate } from '../../src/utils/dateUtils'

test.describe('keyboard Tab entry flow', () => {
  let staffId: string
  let staffWageRate: number
  let chargeOutRate: number
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

    const defaults = await getCompanyDefaults(page)
    chargeOutRate = defaults.charge_out_rate ?? 100

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

    await context.close()
  })

  test('job, tab, hours, tab, description, tab — two rows with verified data', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(`/timesheets/entry?date=${getLatestWeekdayDate()}&staffId=${staffId}`)
    await page.waitForLoadState('networkidle')

    const r0 = await getPhantomRowIndex(page)

    // Row 1
    await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-trigger`).click()
    await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-search`).fill(jobNumber1)
    await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-option-${jobNumber1}`).click()
    await expect(autoId(page, `SmartTimesheetTable-hours-${r0}`)).toBeFocused({ timeout: 3000 })

    await autoId(page, `SmartTimesheetTable-hours-${r0}`).fill('2')
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-description-${r0}`)).toBeFocused({
      timeout: 3000,
    })

    await autoId(page, `SmartTimesheetTable-description-${r0}`).fill('Cutting')
    await page.keyboard.press('Tab')
    await page.waitForResponse(
      (res: Response) => res.url().includes('/cost_lines/') && res.request().method() === 'POST',
      { timeout: 15000 },
    )

    // Row 2
    const r1 = await getPhantomRowIndex(page)
    await autoId(page, `SmartTimesheetTable-jobPicker-${r1}-trigger`).waitFor({ timeout: 5000 })
    await autoId(page, `SmartTimesheetTable-jobPicker-${r1}-trigger`).click()
    await autoId(page, `SmartTimesheetTable-jobPicker-${r1}-search`).fill(jobNumber2)
    await autoId(page, `SmartTimesheetTable-jobPicker-${r1}-option-${jobNumber2}`).click()
    await expect(autoId(page, `SmartTimesheetTable-hours-${r1}`)).toBeFocused({ timeout: 3000 })

    await autoId(page, `SmartTimesheetTable-hours-${r1}`).fill('3.5')
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-description-${r1}`)).toBeFocused({
      timeout: 3000,
    })

    await autoId(page, `SmartTimesheetTable-description-${r1}`).fill('Welding')
    await page.keyboard.press('Tab')
    await page.waitForResponse(
      (res: Response) => res.url().includes('/cost_lines/') && res.request().method() === 'POST',
      { timeout: 15000 },
    )

    await page.waitForLoadState('networkidle')

    // Assert via entry_seq
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
      await expect(row.locator(`[data-automation-id$="-hours"]`)).toHaveValue(hoursText)
      await expect(row.locator(`[data-automation-id$="-description"]`)).toHaveValue(desc)

      const wageText = await row.locator(`[data-automation-id$="-wage"]`).textContent()
      const billText = await row.locator(`[data-automation-id$="-bill"]`).textContent()
      const wageVal = parseFloat(
        (wageText?.match(/\$?([\d,]+\.?\d*)/) ?? ['0'])[1].replace(/,/g, ''),
      )
      const billVal = parseFloat(
        (billText?.match(/\$?([\d,]+\.?\d*)/) ?? ['0'])[1].replace(/,/g, ''),
      )

      expect(wageVal).toBeCloseTo(hrs * staffWageRate, 1)
      expect(billVal).toBeCloseTo(hrs * chargeOutRate, 1)
    }

    await test.step('row 1 data', () => assertRow(1, jobNumber1, '2', 'Cutting', 2))
    await test.step('row 2 data', () => assertRow(2, jobNumber2, '3h 30m', 'Welding', 3.5))
  })
})
