import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getPhantomRowIndex } from '../fixtures/helpers'
import { getLatestWeekdayDate } from '../../src/utils/dateUtils'

test('keyboard Tab flow: job, hours, description, next row', async ({
  authenticatedPage: page,
}) => {
  // --- Setup: create a job and get its number ---
  const jobUrl = await createTestJob(page, 'KbdNav')
  await page.goto(jobUrl.split('?')[0])
  await page.waitForLoadState('networkidle')
  const jobNumText = await autoId(page, 'JobView-job-number').first().innerText()
  const jobNumber = jobNumText.match(/#(\d+)/)?.[1] ?? ''
  expect(jobNumber).toBeTruthy()

  // --- Navigate to timesheet entry ---
  await page.goto(`/timesheets/daily?date=${getLatestWeekdayDate()}`)
  await page.waitForLoadState('networkidle')
  await page.locator('[data-automation-id^="StaffRow-name-"]').first().click()
  await page.waitForURL('**/timesheets/entry**')
  await page.waitForLoadState('networkidle')

  const r0 = await getPhantomRowIndex(page)

  // --- Row 1: pick job, type hours, type description ---
  await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-trigger`).click()
  await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-search`).fill(jobNumber)
  await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-option-${jobNumber}`).click()

  // setJob auto-focuses hours
  await expect(autoId(page, `SmartTimesheetTable-hours-${r0}`)).toBeFocused({ timeout: 3000 })

  // fill hours, Tab to description
  await autoId(page, `SmartTimesheetTable-hours-${r0}`).fill('2')
  await page.keyboard.press('Tab')
  await expect(autoId(page, `SmartTimesheetTable-description-${r0}`)).toBeFocused({ timeout: 3000 })

  // fill description, Tab to next row jobNumber
  await autoId(page, `SmartTimesheetTable-description-${r0}`).fill('Cutting')
  await page.keyboard.press('Tab')

  // Tab from description commits (creates entry) then focuses next phantom job picker
  await expect(autoId(page, `SmartTimesheetTable-jobPicker-${r0}-trigger`)).toBeFocused({
    timeout: 5000,
  })

  console.log('[PASS] keyboard Tab flow completed')
})
