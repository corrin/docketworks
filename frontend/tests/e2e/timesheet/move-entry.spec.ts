import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getPhantomRowIndex } from '../helpers'
import {
  enterHours,
  getLatestWeekdayDate,
  openEntryViaDaily,
  readJobNumber,
  selectJobByNumber,
  waitForEntryGrid,
} from './support'

/**
 * KAN-370: a saved timesheet entry's job is changed from the entry grid.
 * Picking another job on a saved row moves the entry in one PATCH; both
 * jobs' Actuals reflect it; the day's history records it. Reads the synced
 * pay items only: a run of this spec spends no Xero quota.
 */

/** The grid row whose picker shows this job number (rows re-order by entry_seq on reload). */
async function rowIndexOfJob(page: Page, jobNumber: number): Promise<number> {
  const trigger = page
    .locator(
      '[data-automation-id^="SmartTimesheetTable-jobPicker-"][data-automation-id$="-trigger"]',
      { hasText: new RegExp(`^#${jobNumber}(\\D|$)`) },
    )
    .first()
  await trigger.waitFor({ timeout: 15000 })
  const id = await trigger.getAttribute('data-automation-id')
  const match = /jobPicker-(\d+)-trigger/.exec(id ?? '')
  if (!match) throw new Error(`No picker trigger shows #${jobNumber}`)
  return Number(match[1])
}

/** The Actuals tab's time chip as a number. It reads '—' until the cost set
    lands and a currency figure after, zero included, so the figure is the wait. */
async function timeExpensesOnJob(page: Page, jobUrl: string): Promise<number> {
  await page.goto(jobUrl.replace(/\?.*$/, ''))
  await autoId(page, 'JobViewTabs-actual').click()
  const chip = autoId(page, 'JobActualTab-time-expenses')
  await expect(chip).toContainText('$', { timeout: 15000 })
  return Number((await chip.innerText()).replace(/[^0-9.-]/g, ''))
}

test.describe.serial('moving a timesheet entry to another job', () => {
  let sourceUrl = ''
  let sourceNumber = 0
  let destinationUrl = ''
  let destinationNumber = 0
  const date = getLatestWeekdayDate()

  test('create the source and destination jobs', async ({ authenticatedPage: page }) => {
    sourceUrl = await createTestJob(page, 'MoveFrom')
    sourceNumber = await readJobNumber(page)
    destinationUrl = await createTestJob(page, 'MoveTo')
    destinationNumber = await readJobNumber(page)
    expect(destinationNumber).not.toBe(sourceNumber)
  })

  test('add an entry on the source job', async ({ authenticatedPage: page }) => {
    await openEntryViaDaily(page, date)
    const rowIndex = await getPhantomRowIndex(page)
    await selectJobByNumber(page, rowIndex, sourceNumber)
    const createPost = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await enterHours(page, rowIndex, '2')
    expect((await createPost).ok()).toBe(true)
    await expect(autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`)).toContainText(
      `#${sourceNumber}`,
    )
  })

  test('picking the destination on the saved row moves the entry', async ({
    authenticatedPage: page,
  }) => {
    await openEntryViaDaily(page, date)
    const rowIndex = await rowIndexOfJob(page, sourceNumber)

    const movePatch = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'PATCH',
      { timeout: 15000 },
    )
    await selectJobByNumber(page, rowIndex, destinationNumber)
    expect((await movePatch).ok()).toBe(true)

    const trigger = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`)
    await expect(trigger).toContainText(`#${destinationNumber}`)
    // The row carries the destination's charge-out: a repriced, non-zero invoice figure.
    await expect(async () => {
      const bill = autoId(page, `SmartTimesheetTable-bill-${rowIndex}`)
      expect(Number((await bill.innerText()).replace(/[^0-9.-]/g, ''))).toBeGreaterThan(0)
    }).toPass({ timeout: 15000 })

    await page.reload()
    await waitForEntryGrid(page)
    await rowIndexOfJob(page, destinationNumber)
  })

  test("both jobs' Actuals reflect the move", async ({ authenticatedPage: page }) => {
    expect(await timeExpensesOnJob(page, destinationUrl)).toBeGreaterThan(0)
    expect(await timeExpensesOnJob(page, sourceUrl)).toBe(0)
  })

  test("the day's history records the move", async ({ authenticatedPage: page }) => {
    await openEntryViaDaily(page, date)
    const history = page.waitForResponse(
      (response) =>
        response.url().includes('/timesheet/entries/history/') &&
        response.request().method() === 'GET',
      { timeout: 15000 },
    )
    await autoId(page, 'TimesheetEntry-history').click()
    expect((await history).ok()).toBe(true)
    const list = autoId(page, 'TimesheetHistoryDialog-list')
    await expect(list).toBeVisible({ timeout: 15000 })
    await expect(list).toContainText(`Moved from #${sourceNumber} to #${destinationNumber}`)
    await expect(list).toContainText('Entry created')
  })
})
