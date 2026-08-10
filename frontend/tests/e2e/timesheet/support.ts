/** Shared setup for the timesheet-entry cluster (one implementation per concept). */
import type { Page } from '@playwright/test'
import { expect } from '../fixtures/auth'
import { autoId } from '../helpers'

/**
 * Today's local date as YYYY-MM-DD, shifted back to Friday on a weekend —
 * every timesheet spec drives its date off this (v1 dateUtils rule: never
 * toISOString, which shifts NZ dates through UTC).
 */
export function getLatestWeekdayDate(): string {
  const now = new Date()
  const day = now.getDay()
  if (day === 6) now.setDate(now.getDate() - 1)
  if (day === 0) now.setDate(now.getDate() - 2)
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const date = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${date}`
}

/** Daily page → click the first staff row → land on the entry page. */
export async function openEntryViaDaily(page: Page, date: string): Promise<void> {
  await page.goto(`/timesheets/daily?date=${date}`)
  const firstStaff = page.locator('[data-automation-id^="StaffRow-name-"]').first()
  await firstStaff.waitFor({ timeout: 15000 })
  await firstStaff.click()
  await page.waitForURL('**/timesheets/entry**')
  await waitForEntryGrid(page)
}

/** The grid is interactable once it renders and the loading spinner is gone. */
export async function waitForEntryGrid(page: Page): Promise<void> {
  await page.locator('.smart-timesheet-table').waitFor({ state: 'visible', timeout: 60000 })
  await page.waitForFunction(() => !document.querySelector('.animate-spin'), { timeout: 60000 })
}

/** Open row N's job picker and select a job by its number. */
export async function selectJobByNumber(
  page: Page,
  rowIndex: number,
  jobNumber: number | string,
): Promise<void> {
  await autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`).click()
  const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-search`)
  await expect(search).toBeFocused()
  await search.fill(String(jobNumber))
  const option = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-option-${jobNumber}`)
  await option.waitFor({ timeout: 10000 })
  await option.click()
}

/** Type hours into row N and press Enter (the immediate-create gesture). */
export async function enterHours(page: Page, rowIndex: number, hours: string): Promise<void> {
  const input = autoId(page, `SmartTimesheetTable-hours-${rowIndex}`)
  await input.click()
  await page.keyboard.type(hours)
  await page.keyboard.press('Enter')
}
