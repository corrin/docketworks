import { test, expect } from '../fixtures/auth'
import { getCompanyDefaults, getStaffList } from '../fixtures/api'
import { autoId, gridCell, createTestJob } from '../fixtures/helpers'

/**
 * Tests that staff wage_rate includes annual leave loading and that
 * timesheet entries use the loaded rate for cost calculations.
 *
 * Preconditions:
 * - annual_leave_loading > 0 in company defaults
 * - At least one active staff member with base_wage_rate > 0
 * - Backend running the feature/staff-wages branch
 */

function getWeekdayDate(): string {
  const date = new Date()
  const day = date.getDay()
  if (day === 6) date.setDate(date.getDate() - 1)
  if (day === 0) date.setDate(date.getDate() - 2)
  return date.toISOString().split('T')[0]
}

test.describe.serial('staff wage loading', () => {
  let staffId: string
  let baseWageRate: number
  let wageRate: number
  let annualLeaveLoading: number
  let jobNumber: string

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext()
    const page = await context.newPage()

    // Login
    const username = process.env.E2E_TEST_USERNAME
    const password = process.env.E2E_TEST_PASSWORD
    await page.goto('/login')
    await page.locator('#username').fill(username!)
    await page.locator('#password').fill(password!)
    await page.getByRole('button', { name: 'Sign In' }).click()
    await page.waitForURL('**/kanban')

    // Fetch company defaults for annual_leave_loading
    const defaults = await getCompanyDefaults(page)
    annualLeaveLoading = defaults.annual_leave_loading
    console.log(`Annual leave loading: ${annualLeaveLoading}%`)
    if (!annualLeaveLoading || annualLeaveLoading <= 0) {
      throw new Error(
        `annual_leave_loading must be > 0 for this test (got ${annualLeaveLoading}). ` +
          'Set it in company defaults before running.',
      )
    }

    // Fetch staff list and find an active staff member with base_wage_rate > 0
    const staffList = await getStaffList(page)
    const activeStaff = staffList.find(
      (s: { date_left: string | null; base_wage_rate: number }) =>
        !s.date_left && s.base_wage_rate > 0,
    )
    if (!activeStaff) {
      throw new Error(
        'No active staff member with base_wage_rate > 0 found. ' +
          'Ensure at least one staff member has a base wage rate set.',
      )
    }

    staffId = activeStaff.id
    baseWageRate = activeStaff.base_wage_rate
    wageRate = activeStaff.wage_rate
    console.log(
      `Using staff: ${activeStaff.first_name} ${activeStaff.last_name} ` +
        `(id=${staffId}, base_wage_rate=$${baseWageRate}, wage_rate=$${wageRate})`,
    )

    // Create a test job
    const jobUrl = await createTestJob(page, 'WageLoading')
    console.log(`Created job at: ${jobUrl}`)

    // Extract job number
    await page.goto(jobUrl.split('?')[0])
    await page.waitForLoadState('networkidle')
    const jobNumberElement = autoId(page, 'JobView-job-number').first()
    await jobNumberElement.waitFor({ timeout: 10000 })
    const jobNumberText = await jobNumberElement.innerText()
    const match = jobNumberText.match(/#(\d+)/)
    jobNumber = match ? match[1] : ''
    console.log(`Extracted job number: ${jobNumber}`)
    if (!jobNumber) {
      throw new Error(`Failed to extract job number from: "${jobNumberText}"`)
    }

    await context.close()
  })

  test('wage_rate equals base_wage_rate with annual leave loading applied', async () => {
    const expected = Math.round(baseWageRate * (1 + annualLeaveLoading / 100) * 100) / 100
    console.log(
      `Wage rate calculation: $${baseWageRate} * (1 + ${annualLeaveLoading}/100) = $${expected}`,
    )
    console.log(`API wage_rate: $${wageRate}`)
    expect(wageRate).toBeCloseTo(expected, 2)
  })

  test('timesheet entry uses loaded wage_rate for cost calculation', async ({
    authenticatedPage: page,
  }) => {
    const weekday = getWeekdayDate()
    await page.goto(`/timesheets/entry?date=${weekday}&staffId=${staffId}`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Add a new entry
    await autoId(page, 'TimesheetEntryView-add-entry').click()
    await page.waitForTimeout(500)

    // Find the new temp row
    const newRow = page.locator('.ag-row[row-id^="temp_"]').first()
    await newRow.waitFor({ timeout: 10000 })
    const rowId = await newRow.getAttribute('row-id')
    if (!rowId) throw new Error('Failed to get row-id from new row')
    console.log(`New row created with ID: ${rowId}`)

    // Select the test job
    await gridCell(page, rowId, 'jobNumber').click()
    await page.waitForTimeout(300)
    const jobSearchInput = autoId(page, 'TimesheetEntryJobCellEditor-job-search')
    await jobSearchInput.waitFor({ timeout: 5000 })
    await jobSearchInput.fill(jobNumber)
    await page.waitForTimeout(500)
    const jobOption = autoId(page, `TimesheetEntryJobCellEditor-option-${jobNumber}`)
    await jobOption.waitFor({ timeout: 5000 })
    await jobOption.click()
    await page.waitForTimeout(500)

    // Enter 1 hour
    await gridCell(page, rowId, 'hours').click()
    await page.waitForTimeout(200)
    await page.keyboard.type('1')
    await page.keyboard.press('Enter')

    // Wait for recalculation
    await page.waitForTimeout(2000)

    // Read the wage value from the grid cell
    const wageText = await gridCell(page, rowId, 'wage').textContent()
    console.log(`Displayed wage: ${wageText}`)

    // Parse currency value (e.g., "$43.20" -> 43.20)
    const currencyMatch = wageText?.match(/\$?([\d,]+\.?\d*)/)
    const displayedWage = currencyMatch ? parseFloat(currencyMatch[1].replace(/,/g, '')) : 0

    console.log(
      `Wage comparison: displayed=$${displayedWage}, ` +
        `loaded_rate=$${wageRate}, base_rate=$${baseWageRate}`,
    )

    // The displayed wage for 1 hour at ordinary rate should equal the loaded wage_rate
    expect(displayedWage).toBeCloseTo(wageRate, 2)
    // It should NOT equal the base wage rate (unless loading is 0, but we checked that)
    expect(displayedWage).not.toBeCloseTo(baseWageRate, 2)
  })
})
