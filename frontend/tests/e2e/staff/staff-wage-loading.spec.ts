import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getPhantomRowIndex } from '../helpers'
import { getCompanyDefaults, getStaffList } from '../fixtures/api'
import {
  enterHours,
  getLatestWeekdayDate,
  selectJobByNumber,
  waitForEntryGrid,
} from '../timesheet/support'

/**
 * Annual-leave wage loading: Staff.wage_rate is base_wage_rate with the
 * company's annual_leave_loading applied, and the entry grid's wage column
 * prices hours at the LOADED rate, never the base rate.
 *
 * Port deviation from v1: the shared job is created by the first serial test
 * through the standard fixture.
 */

test.describe.serial('staff wage loading', () => {
  let jobNumber = 0
  let loadingPercent = 0
  let staff: { id: string; base: number; loaded: number } | null = null

  test('capture the loading config and a loaded staff member', async ({
    authenticatedPage: page,
  }) => {
    await createTestJob(page, 'WageLoading')
    jobNumber = Number(
      /#(\d+)/.exec(await autoId(page, 'JobView-job-number').first().innerText())?.[1],
    )

    const defaults = await getCompanyDefaults(page)
    loadingPercent = Number(defaults.annual_leave_loading)
    if (!(loadingPercent > 0)) {
      throw new Error(
        `annual_leave_loading must be > 0 for this spec (got ${String(defaults.annual_leave_loading)})`,
      )
    }

    const staffList = await getStaffList(page)
    const candidate = staffList.find(
      (member) => member.date_left === null && Number(member.base_wage_rate) > 0,
    )
    if (!candidate) throw new Error('No active staff member with base_wage_rate > 0')
    staff = {
      id: candidate.id,
      base: Number(candidate.base_wage_rate),
      loaded: Number(candidate.wage_rate),
    }
  })

  test('wage_rate equals base_wage_rate with the loading applied', () => {
    if (!staff) throw new Error('setup did not run')
    const expected = Math.round(staff.base * (1 + loadingPercent / 100) * 100) / 100
    expect(staff.loaded).toBeCloseTo(expected, 2)
  })

  test('a timesheet entry prices at the loaded wage rate', async ({ authenticatedPage: page }) => {
    if (!staff) throw new Error('setup did not run')
    const date = getLatestWeekdayDate()
    await page.goto(`/timesheets/entry?date=${date}&staffId=${staff.id}`)
    await waitForEntryGrid(page)

    const rowIndex = await getPhantomRowIndex(page)
    await selectJobByNumber(page, rowIndex, jobNumber)

    const createPost = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await enterHours(page, rowIndex, '1')
    const response = await createPost
    expect(response.ok(), await response.text()).toBe(true)

    const wageText =
      (await autoId(page, `SmartTimesheetTable-wage-${rowIndex}`).textContent()) ?? ''
    const displayedWage = Number(/\$?([\d,]+\.?\d*)/.exec(wageText)?.[1]?.replace(/,/g, ''))
    expect(displayedWage).toBeCloseTo(staff.loaded, 2)
    expect(Math.abs(displayedWage - staff.base)).toBeGreaterThan(0.005)
  })
})
