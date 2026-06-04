import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { autoId, createTestJob, getPhantomRowIndex } from '../fixtures/helpers'
import { getLatestWeekdayDate } from '../../src/utils/dateUtils'

/**
 * Tests for timesheet entry operations.
 * Creates a job, adds time via daily timesheet, verifies on job's Actuals tab.
 */

// ============================================================================
// Helper Functions
// ============================================================================

async function navigateToActualsTab(page: Page, jobUrl: string): Promise<void> {
  const baseUrl = jobUrl.split('?')[0]
  await page.goto(baseUrl)
  await page.waitForLoadState('networkidle')
  await autoId(page, 'JobViewTabs-actual').click()
  await autoId(page, 'JobActualTab-time-expenses').waitFor({ timeout: 10000 })
}

async function getTimeAndExpensesValue(page: Page): Promise<number> {
  const chip = autoId(page, 'JobActualTab-time-expenses')
  const text = await chip.innerText()
  const match = text.match(/\$?([\d,]+\.?\d*)/)
  return match ? parseFloat(match[1].replace(/,/g, '')) : 0
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

async function selectJobByNumber(page: Page, rowIndex: number, jobNumber: string): Promise<void> {
  await autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`).click()
  const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-search`)
  await search.waitFor({ timeout: 5000 })
  await search.fill(jobNumber)
  const option = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-option-${jobNumber}`)
  await option.waitFor({ timeout: 5000 })
  await option.click()
}

async function selectJobByName(page: Page, rowIndex: number, jobNameSearch: string): Promise<void> {
  await autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-trigger`).click()
  const search = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-search`)
  await search.waitFor({ timeout: 5000 })
  await search.fill(jobNameSearch)
  const list = autoId(page, `SmartTimesheetTable-jobPicker-${rowIndex}-list`)
  await list.waitFor({ timeout: 5000 })
  const firstOption = list
    .locator(`[data-automation-id^="SmartTimesheetTable-jobPicker-${rowIndex}-option-"]`)
    .first()
  await firstOption.waitFor({ timeout: 5000 })
  await firstOption.click()
}

async function enterHours(page: Page, rowIndex: number, hours: string): Promise<void> {
  const hoursInput = autoId(page, `SmartTimesheetTable-hours-${rowIndex}`)
  await hoursInput.click()
  await page.keyboard.type(hours)
  await page.keyboard.press('Enter')
}

async function setRateMultiplier(
  page: Page,
  rowIndex: number,
  rate: 'Ord' | '1.5' | '2.0' | 'Unpaid',
): Promise<void> {
  // shadcn Select renders the listbox into a Radix portal at document.body.
  // Open the trigger, then pick the labelled option.
  await autoId(page, `SmartTimesheetTable-rate-${rowIndex}`).click()
  const optionLabel = rate === 'Ord' ? 'Ord' : rate === 'Unpaid' ? 'Unpaid' : `${rate}x`
  await page.getByRole('option', { name: optionLabel }).click()
}

async function getPayItemValue(page: Page, rowIndex: number): Promise<string> {
  const cell = autoId(page, `SmartTimesheetTable-payItem-${rowIndex}`)
  return (await cell.textContent()) ?? ''
}

/**
 * Wait for the in-flight POST that creates a phantom-row entry. Once the
 * server responds, the row is replaced with the canonical version and a fresh
 * phantom appears at the next index.
 */
async function waitForCreatePost(page: Page, timeout = 15000): Promise<void> {
  await page.waitForResponse(
    (res) => res.url().includes('/cost_lines/') && res.request().method() === 'POST',
    { timeout },
  )
}

// ============================================================================
// Test Suite: Timesheet Entry Operations
// ============================================================================

test.describe.serial('timesheet entry operations', () => {
  let jobUrl: string
  let jobNumber: string

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

    jobUrl = await createTestJob(page, 'Timesheet')
    console.log(`Created job at: ${jobUrl}`)

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

  test('verify initial Time & Expenses is zero', async ({ authenticatedPage: page }) => {
    await navigateToActualsTab(page, jobUrl)

    const timeExpenses = await getTimeAndExpensesValue(page)
    console.log(`Initial Time & Expenses: $${timeExpenses}`)
    expect(timeExpenses).toBe(0)
  })

  test('add timesheet entry for the test job', async ({ authenticatedPage: page }) => {
    await navigateToTimesheetEntry(page)

    const rowIndex = await getPhantomRowIndex(page)
    console.log(`Phantom row index: ${rowIndex}`)

    await selectJobByNumber(page, rowIndex, jobNumber)
    await enterHours(page, rowIndex, '2')
    await waitForCreatePost(page)

    // After save the row is at the same index; the phantom moved to rowIndex+1.
    // Read the saved row's hours back from its rendered cell. The Hours column
    // is an Input bound to the row's quantity; on a saved row it will display
    // "2" (HoursCell formats whole numbers with no decimal).
    const hoursInput = autoId(page, `SmartTimesheetTable-hours-${rowIndex}`)
    await expect(hoursInput).toHaveValue(/^2/)
    console.log(`Added 2 hours to job ${jobNumber}`)
  })

  test('edit description on the saved row persists after reload', async ({
    authenticatedPage: page,
  }) => {
    await navigateToTimesheetEntry(page)

    // The previous test added a row for `jobNumber`; it sits just before the
    // always-present phantom row. SmartTimesheetTable orders entries with the
    // phantom last, so saved-row index = phantomIndex - 1.
    const phantomIndex = await getPhantomRowIndex(page)
    expect(phantomIndex).toBeGreaterThan(0)
    const savedRowIndex = phantomIndex - 1

    const newDesc = `e2e desc ${Date.now()}`
    const descCell = autoId(page, `SmartTimesheetTable-description-${savedRowIndex}`)

    // Click into the description, replace its contents, press Enter.
    // Pressing Enter must blur the field, which triggers setDescription →
    // commit → autosave → PATCH /cost_lines/{id}.
    await descCell.click()
    await page.keyboard.press('ControlOrMeta+a')
    await page.keyboard.type(newDesc)

    const patchPromise = page.waitForResponse(
      (res) =>
        res.url().includes('/cost_lines/') &&
        res.request().method() === 'PATCH' &&
        res.status() === 200,
      { timeout: 15000 },
    )
    await page.keyboard.press('Enter')
    await patchPromise
    console.log(`PATCHed description to: "${newDesc}"`)

    // Reload to prove the new description came back from the server, not just
    // from the optimistic in-memory update.
    await page.reload()
    await page.waitForLoadState('networkidle')

    const descAfterReload = autoId(page, `SmartTimesheetTable-description-${savedRowIndex}`)
    await expect(descAfterReload).toHaveValue(newDesc)
  })

  test('verify timesheet entry appears on job Actuals tab', async ({ authenticatedPage: page }) => {
    await navigateToActualsTab(page, jobUrl)

    const timeExpenses = await getTimeAndExpensesValue(page)
    console.log(`Time & Expenses after entry: $${timeExpenses}`)
    expect(timeExpenses).toBeGreaterThan(0)
  })
})

// ============================================================================
// Test Suite: Xero Pay Item Validation
// ============================================================================

test.describe.serial('xero pay item validation', () => {
  let testJobNumber: string

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

    const jobUrl = await createTestJob(page, 'PayItem')
    console.log(`Created job for pay item tests at: ${jobUrl}`)

    await page.goto(jobUrl.split('?')[0])
    await page.waitForLoadState('networkidle')
    const jobNumberElement = autoId(page, 'JobView-job-number').first()
    await jobNumberElement.waitFor({ timeout: 10000 })
    const jobNumberText = await jobNumberElement.innerText()
    const match = jobNumberText.match(/#(\d+)/)
    testJobNumber = match ? match[1] : ''
    console.log(`Extracted job number for pay item tests: ${testJobNumber}`)
    if (!testJobNumber) {
      throw new Error(`Failed to extract job number from: "${jobNumberText}"`)
    }

    await context.close()
  })

  test('annual leave job defaults to Annual Leave pay item', async ({
    authenticatedPage: page,
  }) => {
    await navigateToTimesheetEntry(page)
    const rowIndex = await getPhantomRowIndex(page)
    console.log(`Phantom row index for Annual Leave test: ${rowIndex}`)

    await selectJobByName(page, rowIndex, 'Annual Leave')
    await enterHours(page, rowIndex, '4')
    await waitForCreatePost(page)

    const payItem = await getPayItemValue(page, rowIndex)
    console.log(`Annual Leave entry pay item: "${payItem}"`)
    expect(payItem).toBe('Annual Leave')
  })

  test('regular job defaults to Ordinary Time pay item', async ({ authenticatedPage: page }) => {
    await navigateToTimesheetEntry(page)
    const rowIndex = await getPhantomRowIndex(page)
    console.log(`Phantom row index for regular job test: ${rowIndex}`)

    await selectJobByNumber(page, rowIndex, testJobNumber)
    await enterHours(page, rowIndex, '2')
    await waitForCreatePost(page)

    const payItem = await getPayItemValue(page, rowIndex)
    console.log(`Regular job entry pay item: "${payItem}"`)
    expect(payItem).toBe('Ordinary Time')
  })

  test('changing rate to 2.0 updates pay item to Double Time', async ({
    authenticatedPage: page,
  }) => {
    await navigateToTimesheetEntry(page)

    // The previous test left a saved entry on testJobNumber, but the staff's
    // day already had other entries — its row index isn't deterministic. Find
    // it by matching the picker trigger text (`#${testJobNumber}`) and read
    // the row index out of the trigger's automation-id.
    const triggers = page
      .locator(
        '[data-automation-id^="SmartTimesheetTable-jobPicker-"][data-automation-id$="-trigger"]',
      )
      .filter({ hasText: `#${testJobNumber}` })
    await triggers.first().waitFor({ timeout: 10000 })
    const triggerId = await triggers.first().getAttribute('data-automation-id')
    const match = triggerId?.match(/jobPicker-(\d+)-trigger/)
    const rowIndex = match ? Number(match[1]) : -1
    expect(rowIndex).toBeGreaterThanOrEqual(0)
    console.log(`Found regular-job row at index ${rowIndex} (#${testJobNumber})`)

    await setRateMultiplier(page, rowIndex, '2.0')

    // Rate change kicks off a PATCH; wait for it before reading the pay item.
    await page.waitForResponse(
      (res) =>
        res.url().includes('/cost_lines/') && ['PATCH', 'PUT'].includes(res.request().method()),
      { timeout: 15000 },
    )

    const payItem = await getPayItemValue(page, rowIndex)
    console.log(`After rate change to 2.0, pay item: "${payItem}"`)
    expect(['Double Time', 'Overtime (2.0)']).toContain(payItem)
  })
})
