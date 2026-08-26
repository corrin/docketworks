import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getPhantomRowIndex } from '../helpers'
import {
  enterHours,
  getLatestWeekdayDate,
  openEntryViaDaily,
  readJobNumber,
  selectJobByNumber,
} from './support'

/**
 * Timesheet entry operations end to end: create an entry against a fresh
 * job, edit its description, and see the hours on the job's Actuals tab.
 *
 * Port deviations from v1, each deliberate:
 * - The shared job is created by the first serial test through the standard
 *   authenticated fixture, not a hand-rolled beforeAll login.
 * - The Xero pay-item scenarios keep v1's assertions but read the hidden
 *   payItem span after the row is SAVED (the span resolves the server-picked
 *   pay item; drafts render it empty).
 */

test.describe.serial('timesheet entry operations', () => {
  let jobUrl = ''
  let jobNumber = 0
  const date = getLatestWeekdayDate()

  test('create the shared job and verify initial time & expenses is zero', async ({
    authenticatedPage: page,
  }) => {
    jobUrl = await createTestJob(page, 'Timesheet')
    jobNumber = await readJobNumber(page)

    await autoId(page, 'JobViewTabs-actual').click()
    // The chip renders '—' until the summary query lands; wait for money.
    const chip = autoId(page, 'JobActualTab-time-expenses')
    await expect(chip).toContainText('$', { timeout: 15000 })
    const amount = Number((await chip.innerText()).replace(/[^0-9.-]/g, ''))
    expect(amount).toBe(0)
  })

  test('add a timesheet entry against the job', async ({ authenticatedPage: page }) => {
    await openEntryViaDaily(page, date)
    const rowIndex = await getPhantomRowIndex(page)
    await selectJobByNumber(page, rowIndex, jobNumber)

    const createPost = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await enterHours(page, rowIndex, '2')
    const response = await createPost
    expect(response.ok()).toBe(true)

    await expect(autoId(page, `SmartTimesheetTable-hours-${rowIndex}`)).toHaveValue(/^2/)
  })

  test('editing the description persists across a reload', async ({ authenticatedPage: page }) => {
    await openEntryViaDaily(page, date)
    const phantomIndex = await getPhantomRowIndex(page)
    expect(phantomIndex).toBeGreaterThan(0)
    const savedRowIndex = phantomIndex - 1

    const description = autoId(page, `SmartTimesheetTable-description-${savedRowIndex}`)
    await description.click()
    await page.keyboard.press('ControlOrMeta+a')
    const newDesc = `e2e desc ${Date.now()}`
    await page.keyboard.type(newDesc)

    const patch = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') &&
        response.request().method() === 'PATCH' &&
        response.status() === 200,
      { timeout: 15000 },
    )
    await page.keyboard.press('Enter')
    await patch

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(autoId(page, `SmartTimesheetTable-description-${savedRowIndex}`)).toHaveValue(
      newDesc,
    )
  })

  test('the entry appears on the job Actuals tab', async ({ authenticatedPage: page }) => {
    await page.goto(jobUrl.replace(/\?.*$/, ''))
    await autoId(page, 'JobViewTabs-actual').click()
    // Poll: the chip shows '—' (which parses to 0) until the summary lands.
    const chip = autoId(page, 'JobActualTab-time-expenses')
    await expect(async () => {
      const amount = Number((await chip.innerText()).replace(/[^0-9.-]/g, ''))
      expect(amount).toBeGreaterThan(0)
    }).toPass({ timeout: 15000 })
  })
})

test.describe.serial('xero pay item validation', () => {
  let jobNumber = 0
  const date = getLatestWeekdayDate()

  test('create the shared job', async ({ authenticatedPage: page }) => {
    await createTestJob(page, 'PayItem')
    jobNumber = await readJobNumber(page)
  })

  test('an Annual Leave entry maps to the Annual Leave pay item', async ({
    authenticatedPage: page,
  }) => {
    await openEntryViaDaily(page, date)
    const rowIndex = await getPhantomRowIndex(page)

    // The leave job is found by NAME (it exists in the restore data).
    await autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`).click()
    const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-search`)
    await expect(search).toBeFocused()
    await search.fill('Annual Leave')
    const firstOption = page
      .locator(`[data-automation-id^="SmartTimesheetTable-jobPicker-${rowIndex}-option-"]`)
      .first()
    await firstOption.waitFor({ timeout: 10000 })
    await firstOption.click()

    const createPost = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await enterHours(page, rowIndex, '4')
    expect((await createPost).ok()).toBe(true)

    await expect(autoId(page, `SmartTimesheetTable-payItem-${rowIndex}`)).toHaveText(
      'Annual Leave',
      { timeout: 10000 },
    )
  })

  test('a regular entry maps to Ordinary Time', async ({ authenticatedPage: page }) => {
    await openEntryViaDaily(page, date)
    const rowIndex = await getPhantomRowIndex(page)
    await selectJobByNumber(page, rowIndex, jobNumber)

    const createPost = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await enterHours(page, rowIndex, '2')
    expect((await createPost).ok()).toBe(true)

    await expect(autoId(page, `SmartTimesheetTable-payItem-${rowIndex}`)).toHaveText(
      'Ordinary Time',
      { timeout: 10000 },
    )
  })

  test('changing the rate to 2.0x maps to the double-time pay item', async ({
    authenticatedPage: page,
  }) => {
    await openEntryViaDaily(page, date)

    // Find the regular job's saved row by its picker trigger text.
    const trigger = page
      .locator(
        '[data-automation-id^="SmartTimesheetTable-jobPicker-"][data-automation-id$="-trigger"]',
      )
      .filter({ hasText: `#${jobNumber}` })
      .first()
    await trigger.waitFor({ timeout: 15000 })
    const triggerId = await trigger.getAttribute('data-automation-id')
    const match = /jobPicker-(\d+)-trigger/.exec(triggerId ?? '')
    if (!match) throw new Error(`Could not parse row index from ${triggerId}`)
    const rowIndex = Number(match[1])

    await autoId(page, `SmartTimesheetTable-rate-${rowIndex}`).click()
    const patch = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') &&
        ['PATCH', 'PUT'].includes(response.request().method()),
      { timeout: 15000 },
    )
    await page.getByRole('option', { name: '2.0x' }).click()
    expect((await patch).ok()).toBe(true)

    const payItem = autoId(page, `SmartTimesheetTable-payItem-${rowIndex}`)
    await expect(async () => {
      const text = (await payItem.textContent()) ?? ''
      expect(['Double Time', 'Overtime (2.0)']).toContain(text)
    }).toPass({ timeout: 10000 })
  })
})
