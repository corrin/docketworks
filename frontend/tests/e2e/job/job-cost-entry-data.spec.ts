import type { Page, Response, Locator } from '@playwright/test'
import { z } from 'zod'

import { test, expect } from '../fixtures/auth'
import { getCompanyDefaults, getJobLabourRates, getMe } from '../fixtures/api'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'

/**
 * Cost entry data-first scenarios: the quote draft lifecycle under failure,
 * and estimate/actual entry reconciling the grid against the persisted cost
 * set (including the actual tab's stock-consume material path).
 *
 * Port deviations from v1, each deliberate:
 * - Labour seeding POSTs the live actual cost-line create with
 *   `meta.created_from_timesheet` (the same pricing pipeline server-side).
 *   v1 seeded via `/api/job/timesheet/entries/`, an operation v1's own
 *   frontend never called — dead surface the ledger says not to port. The
 *   Xero pay item resolves server-side, so v1's ordinary-pay-item fetch
 *   drops out with it.
 * - The seeded staff member is the authenticated E2E user (`/api/accounts/me/`).
 *   v1 read `/api/accounts/staff/`, which belongs to the unported staff
 *   slice, and `/api/timesheets/staff/` is superuser-gated. The wage-side
 *   assertion therefore checks the line is priced coherently (unit_cost > 0
 *   and equal to the meta wage_rate the pricing pipeline stamped); the
 *   charge-out side stays independently asserted from the job's labour rates.
 * - The row-exit gesture is a click on the tab's section heading: this grid
 *   has no custom Tab-to-next-row handler (Tab from unit-rev lands on the
 *   row's own delete button, which is not a row exit). v1's deliberate
 *   unawaited-create race disappears with it — creation only fires at the
 *   explicit row exit, so no earlier field can trigger a stale response.
 * - Cell lookups use the textarea/automation-id contract; `data-grid-col`
 *   sits on the td (the navigation cell), not on the control, so it cannot
 *   be filled or focus-asserted directly.
 * - Editing a consumed material's quantity adjusts the Stock row by the
 *   difference (ledgered v2 improvement); like v1, the spec asserts the
 *   cost set, not stock levels.
 */

const decimalish = z.union([z.number(), z.string()])

const costLineSchema = z.object({
  id: z.string(),
  kind: z.enum(['material', 'time', 'adjust']),
  desc: z.string().nullable(),
  quantity: decimalish,
  unit_cost: decimalish,
  unit_rev: decimalish,
  total_cost: decimalish,
  total_rev: decimalish,
  approved: z.boolean().optional(),
  ext_refs: z.record(z.string(), z.unknown()).optional(),
  meta: z.record(z.string(), z.unknown()).optional(),
})
type CostLine = z.infer<typeof costLineSchema>

const costSetSchema = z.object({ cost_lines: z.array(costLineSchema) })
type CostSet = z.infer<typeof costSetSchema>

const stockItemSchema = z.object({
  id: z.string(),
  item_code: z.string().nullable(),
  description: z.string(),
  unit_cost: decimalish,
  unit_revenue: decimalish,
})
type StockItem = z.infer<typeof stockItemSchema>

const stockSearchSchema = z.object({ results: z.array(stockItemSchema) })

const stockPatchBodySchema = z
  .object({ ext_refs: z.object({ stock_id: z.string().optional() }).optional() })
  .nullable()

const money = (value: unknown, label = 'numeric value'): number => {
  if (value === null || value === undefined || value === '') {
    throw new Error(`Missing ${label}`)
  }
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) {
    throw new Error(`Invalid ${label}: ${JSON.stringify(value)}`)
  }
  return numberValue
}
const roundMoney = (value: number): number => Math.round(value * 100) / 100
const lineCost = (quantity: number, unitCost: number): number => quantity * unitCost
const lineRevenue = (quantity: number, unitRev: number): number => quantity * unitRev

/** Local date, walked back to the latest weekday, as YYYY-MM-DD. */
function latestWeekdayDate(): string {
  const date = new Date()
  while (date.getDay() === 0 || date.getDay() === 6) {
    date.setDate(date.getDate() - 1)
  }
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

const TAB_HEADINGS = {
  estimate: 'Estimate Details',
  quote: 'Quote Details',
  actual: 'Actual Costs',
} as const

type CostTab = keyof typeof TAB_HEADINGS

async function navigateToCostTab(page: Page, jobUrl: string, tab: CostTab): Promise<void> {
  await page.goto(`${jobUrl.split('?')[0]}?tab=${tab}`)
  const tabButton = autoId(page, `JobViewTabs-${tab}`)
  await tabButton.waitFor({ state: 'visible', timeout: 10000 })
  await tabButton.click()
  await page.getByRole('heading', { name: TAB_HEADINGS[tab] }).waitFor({ timeout: 10000 })
  await page.locator('[data-row-id]').last().waitFor({ state: 'visible', timeout: 10000 })
}

/** Leave the focused row so a completed draft POSTs (row-exit persistence). */
async function exitRow(page: Page, tab: CostTab): Promise<void> {
  await page.getByRole('heading', { name: TAB_HEADINGS[tab] }).click()
}

async function fetchCostSet(page: Page, jobId: string, kind: CostTab): Promise<CostSet> {
  const response = await page.request.get(`/api/job/jobs/${jobId}/cost_sets/${kind}/`)
  expect(response.ok(), await response.text()).toBe(true)
  return costSetSchema.parse(await response.json())
}

async function fetchStock(page: Page, query: string, description: string): Promise<StockItem> {
  const response = await page.request.get(
    `/api/purchasing/stock/search/?q=${encodeURIComponent(query)}&page=1&page_size=50`,
  )
  expect(response.ok(), await response.text()).toBe(true)
  const body = stockSearchSchema.parse(await response.json())
  const item = body.results.find((candidate) => candidate.description.includes(description))
  if (!item) throw new Error(`No stock item found for query "${query}"`)
  return item
}

async function createCostLineByApi(
  page: Page,
  jobId: string,
  kind: 'estimate' | 'actual',
  payload: Record<string, unknown>,
): Promise<CostLine> {
  const response = await page.request.post(`/api/job/jobs/${jobId}/cost_sets/${kind}/cost_lines/`, {
    data: payload,
  })
  expect(response.ok(), await response.text()).toBe(true)
  return costLineSchema.parse(await response.json())
}

/**
 * Seed a timesheet labour line through the live actual cost-line create:
 * `meta.created_from_timesheet` routes it through the one rate pipeline, so
 * unit cost/rev and the pay item are server-derived exactly as a timesheet
 * write derives them.
 */
async function createTimesheetLabourByApi(
  page: Page,
  payload: {
    jobId: string
    staffId: string
    labourSubtype: string
    date: string
    hours: number
    description: string
  },
): Promise<string> {
  const line = await createCostLineByApi(page, payload.jobId, 'actual', {
    kind: 'time',
    desc: payload.description,
    quantity: payload.hours,
    accounting_date: payload.date,
    ext_refs: {},
    labour_subtype: payload.labourSubtype,
    meta: {
      created_from_timesheet: true,
      staff_id: payload.staffId,
      date: payload.date,
      is_billable: true,
      wage_rate_multiplier: 1,
    },
  })
  if (!line.id) throw new Error('Timesheet labour seed did not return a cost line id')
  return line.id
}

async function clickAddRow(page: Page): Promise<string> {
  const selectItemButton = page.getByRole('button', { name: 'Select Item' }).last()
  await selectItemButton.waitFor({ timeout: 10000 })
  const row = selectItemButton.locator('xpath=ancestor::*[@data-row-id][1]')
  const rowId = await row.getAttribute('data-row-id')
  if (!rowId) throw new Error('Could not find phantom row')
  await selectItemButton.click()
  return rowId
}

/** Descriptions live in textareas, so their value is not matchable as row text. */
async function findRowIndexByDescription(page: Page, description: string): Promise<number> {
  const rows = page.locator('[data-automation-id^="DataTable-row-"]')
  const count = await rows.count()

  for (let i = 0; i < count; i += 1) {
    const textarea = rows.nth(i).locator('textarea').first()
    const value = await textarea.inputValue().catch(() => '')
    if (value === description) return i
  }

  return -1
}

/** Retry the description scan: a just-created line swaps its draft row for a
 * server row mid-render, and a single pass can read rows between frames. */
async function waitForRowIndexByDescription(page: Page, description: string): Promise<number> {
  await expect(async () => {
    expect(await findRowIndexByDescription(page, description)).toBeGreaterThanOrEqual(0)
  }).toPass({ timeout: 10000 })
  return findRowIndexByDescription(page, description)
}

async function expectRowAbsent(page: Page, description: string): Promise<void> {
  expect(await findRowIndexByDescription(page, description)).toBe(-1)
}

async function countRowsByDescription(page: Page, description: string): Promise<number> {
  const rows = page.locator('[data-automation-id^="DataTable-row-"]')
  const count = await rows.count()
  let matches = 0

  for (let i = 0; i < count; i += 1) {
    const textarea = rows.nth(i).locator('textarea').first()
    const value = await textarea.inputValue().catch(() => '')
    if (value === description) matches += 1
  }

  return matches
}

function waitForCostLineCreate(page: Page): Promise<Response> {
  return page.waitForResponse(
    (res) =>
      res.url().includes('/cost_lines') &&
      res.request().method() === 'POST' &&
      [200, 201].includes(res.status()),
  )
}

function waitForAnyCostLineCreate(page: Page): Promise<Response> {
  return page.waitForResponse(
    (res) => res.url().includes('/cost_lines') && res.request().method() === 'POST',
  )
}

function waitForCostLinePatch(page: Page): Promise<Response> {
  return page.waitForResponse(
    (res) =>
      res.url().includes('/api/job/cost_lines/') &&
      res.request().method() === 'PATCH' &&
      res.status() === 200,
  )
}

function waitForCostLineStockPatch(page: Page, stockId: string): Promise<Response> {
  return page.waitForResponse((res) => {
    if (
      !res.url().includes('/api/job/cost_lines/') ||
      res.request().method() !== 'PATCH' ||
      res.status() !== 200
    ) {
      return false
    }

    const body = stockPatchBodySchema.safeParse(res.request().postDataJSON())
    return body.success && body.data?.ext_refs?.stock_id === stockId
  })
}

function waitForCostLineDelete(page: Page): Promise<Response> {
  return page.waitForResponse(
    (res) =>
      res.url().includes('/api/job/cost_lines/') &&
      res.request().method() === 'DELETE' &&
      res.status() === 204,
  )
}

function waitForStockConsume(page: Page): Promise<Response> {
  return page.waitForResponse(
    (res) =>
      res.url().includes('/api/purchasing/stock/') &&
      res.url().includes('/consume/') &&
      res.request().method() === 'POST' &&
      res.status() === 200,
  )
}

async function selectItemFromNewRow(page: Page, query: string, optionText: string): Promise<void> {
  await clickAddRow(page)
  const search = page.getByPlaceholder('Search items by description, code, or type...')
  await search.waitFor({ timeout: 10000 })
  await search.fill(query)
  const option = page.locator('[data-automation-id^="ItemSelect-option-"]').filter({
    hasText: optionText,
  })
  await option.first().waitFor({ timeout: 10000 })
  await option.first().click()
}

async function editNumberCell(
  page: Page,
  rowIndex: number,
  field: 'quantity' | 'unit-cost' | 'unit-rev',
  value: string,
): Promise<void> {
  const input = autoId(page, `SmartCostLinesTable-${field}-${rowIndex}`)
  await input.click()
  await input.fill(value)
  const patch = waitForCostLinePatch(page)
  await page.keyboard.press('Tab')
  await patch
}

function rowNumberInput(row: Locator, field: 'quantity' | 'unit-cost' | 'unit-rev'): Locator {
  return row.locator(`[data-automation-id^="SmartCostLinesTable-${field}-"]`)
}

async function createAdjustmentFromNewRow(
  page: Page,
  tab: CostTab,
  description: string,
  quantity: string,
  unitCost: string,
  unitRevenue: string,
  expectedStatus = 201,
): Promise<string> {
  const rows = page.locator('[data-automation-id^="DataTable-row-"]')
  const initialRowCount = await rows.count()
  const trailingRow = rows.last()
  const draftRowId = await trailingRow.getAttribute('data-row-id')
  if (!draftRowId) throw new Error('Trailing cost row has no stable row ID')
  const trailingDescription = trailingRow.locator('textarea').first()

  await trailingDescription.click()
  await page.keyboard.type(description)
  // Business risk: promoting the phantom with a different row identity
  // replaces the textarea after its first character, moving focus and
  // truncating normal keyboard input.
  const promotedRow = page.locator(`[data-row-id="${draftRowId}"]`)
  const promotedDescription = promotedRow.locator('textarea').first()
  await expect(promotedDescription).toBeFocused()
  await expect(promotedDescription).toHaveValue(description)

  // Business risk: API-seeded adjustments bypass the phantom-row promotion
  // that keeps entry continuous — a promotion that eats the phantom breaks
  // continuous data entry.
  await expect(rows).toHaveCount(initialRowCount + 1)
  await expect(rows.last().locator('textarea').first()).toHaveValue('')

  const quantityInput = rowNumberInput(promotedRow, 'quantity')
  await quantityInput.fill(quantity)
  const unitCostInput = rowNumberInput(promotedRow, 'unit-cost')
  await unitCostInput.fill(unitCost)
  const unitRevenueInput = rowNumberInput(promotedRow, 'unit-rev')
  await unitRevenueInput.fill(unitRevenue)

  // Creation fires on row EXIT only, so no earlier field edit can race a
  // create response into the draft lifecycle.
  const createResponse = waitForAnyCostLineCreate(page)
  await exitRow(page, tab)
  const response = await createResponse
  const responseBody = await response.text()
  expect(response.status(), responseBody).toBe(expectedStatus)
  return draftRowId
}

async function deleteRow(page: Page, rowIndex: number): Promise<void> {
  page.once('dialog', (dialog) => void dialog.accept())
  const deleteResponse = waitForCostLineDelete(page)
  await autoId(page, `SmartCostLinesTable-delete-${rowIndex}`).click()
  await deleteResponse
}

function findLine(lines: CostLine[], description: string, kind?: CostLine['kind']): CostLine {
  const line = lines.find((candidate) => {
    return candidate.desc === description && (!kind || candidate.kind === kind)
  })
  if (!line) throw new Error(`Could not find ${kind ?? 'any'} cost line "${description}"`)
  return line
}

function expectLineTotals(line: CostLine): void {
  const quantity = money(line.quantity)
  const unitCost = money(line.unit_cost)
  const unitRev = money(line.unit_rev)
  expect(money(line.total_cost)).toBeCloseTo(quantity * unitCost, 2)
  expect(money(line.total_rev)).toBeCloseTo(quantity * unitRev, 2)
}

function expectCostSetTotals(lines: CostLine[]): void {
  for (const line of lines) expectLineTotals(line)
}

function sumCost(lines: CostLine[]): number {
  return lines.reduce((total, line) => total + money(line.total_cost), 0)
}

function sumRevenue(lines: CostLine[]): number {
  return lines.reduce((total, line) => total + money(line.total_rev), 0)
}

async function findWorkshopRate(page: Page, jobId: string) {
  const labourRates = await getJobLabourRates(page, jobId)
  const workshopRate = labourRates.find((rate) => rate.is_workshop)
  if (!workshopRate) throw new Error('Job has no workshop labour rate')
  return workshopRate
}

test.describe('job cost entry data-first scenarios', () => {
  test.describe('quote draft failure', () => {
    test.use({
      // The forced 503 logs the browser's own resource error; the app itself
      // toasts the failure rather than console.erroring it.
      expectedConsoleErrors: ['Failed to load resource: the server responded with a status of 503'],
    })

    test('retains local drafts through delete, failed save, and retry', async ({
      authenticatedPage: page,
      sharedEditJobUrl,
    }) => {
      const jobId = getJobIdFromUrl(sharedEditJobUrl)
      const discardedDesc = `E2E quote discarded ${Date.now()}`
      const adjustmentDesc = `E2E quote adjustment ${Date.now()}`

      await navigateToCostTab(page, sharedEditJobUrl, 'quote')

      const rows = page.locator('[data-automation-id^="DataTable-row-"]')
      const initialRowCount = await rows.count()
      const discardedRow = rows.last()
      const discardedRowId = await discardedRow.getAttribute('data-row-id')
      if (!discardedRowId) throw new Error('Trailing quote row has no stable row ID')
      await discardedRow.locator('textarea').first().fill(discardedDesc)
      await expect(rows).toHaveCount(initialRowCount + 1)
      await autoId(page, `SmartCostLinesTable-delete-${initialRowCount - 1}`).click()
      await expect(page.locator(`[data-row-id="${discardedRowId}"]`)).toHaveCount(0)
      await expect(rows).toHaveCount(initialRowCount)

      const createUrl = `**/api/job/jobs/${jobId}/cost_sets/quote/cost_lines/`
      let failNextCreate = true
      await page.route(createUrl, async (route) => {
        if (route.request().method() === 'POST' && failNextCreate) {
          failNextCreate = false
          await route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'E2E forced create failure' }),
          })
          return
        }
        await route.continue()
      })

      const failedDraftId = await createAdjustmentFromNewRow(
        page,
        'quote',
        adjustmentDesc,
        '4',
        '-11',
        '-17',
        503,
      )
      await page.unroute(createUrl)

      const failedRow = page.locator(`[data-row-id="${failedDraftId}"]`)
      await expect(failedRow).toContainText('Save failed')
      // Re-entering the row and leaving it again retries the create.
      const retryResponse = waitForAnyCostLineCreate(page)
      await rowNumberInput(failedRow, 'unit-rev').focus()
      await exitRow(page, 'quote')
      const response = await retryResponse
      const responseBody = await response.text()
      expect(response.status(), responseBody).toBe(201)

      const quote = await fetchCostSet(page, jobId, 'quote')
      const adjustment = findLine(quote.cost_lines, adjustmentDesc, 'adjust')
      expect(money(adjustment.quantity)).toBeCloseTo(4, 2)
      expect(money(adjustment.unit_cost)).toBeCloseTo(-11, 2)
      expect(money(adjustment.unit_rev)).toBeCloseTo(-17, 2)
      expect(quote.cost_lines.some((line) => line.desc === discardedDesc)).toBe(false)
    })
  })

  test('estimate create edit replace delete reconciles persisted costs', async ({
    authenticatedPage: page,
  }) => {
    const jobUrl = await createTestJob(page, 'EstimateData')
    const jobId = getJobIdFromUrl(jobUrl)
    const defaults = await getCompanyDefaults(page)
    // Labour revenue comes from the job's per-subtype rate, not company defaults.
    const workshopRate = await findWorkshopRate(page, jobId)
    const stockA = await fetchStock(page, 'M8 ZINC', 'M8 ZINC WING NUT')
    const stockB = await fetchStock(page, 'M10 X 25 BLACK', 'M10 X 25 BLACK')
    const accountingDate = latestWeekdayDate()

    const labourQuantity = '2.5'
    const adjustmentDesc = `E2E estimate adjustment ${Date.now()}`
    const deletedDesc = `E2E estimate deleted ${Date.now()}`
    const expectedEstimateCost =
      lineCost(Number(labourQuantity), money(defaults.wage_rate)) +
      lineCost(10, money(stockB.unit_cost)) +
      lineCost(2, -15)
    const expectedEstimateRevenue =
      lineRevenue(Number(labourQuantity), money(workshopRate.charge_out_rate)) +
      lineRevenue(10, money(stockB.unit_revenue)) +
      lineRevenue(2, -25)

    await navigateToCostTab(page, jobUrl, 'estimate')

    await clickAddRow(page)
    const labourCreate = waitForCostLineCreate(page)
    await page
      .locator('[data-automation-id^="ItemSelect-option-labour"]')
      .filter({ hasText: 'Workshop' })
      .click()
    await labourCreate

    const labourIndex = await waitForRowIndexByDescription(page, 'Workshop')
    await editNumberCell(page, labourIndex, 'quantity', labourQuantity)

    const materialCreate = waitForCostLineCreate(page)
    await selectItemFromNewRow(page, 'M8 ZINC', 'M8 ZINC WING NUT')
    await materialCreate

    let materialIndex = await waitForRowIndexByDescription(page, stockA.description)
    await editNumberCell(page, materialIndex, 'quantity', '10')

    await autoId(page, `SmartCostLinesTable-item-${materialIndex}`).locator('button').click()
    const replaceSearch = page.getByPlaceholder('Search items by description, code, or type...')
    await replaceSearch.waitFor({ timeout: 10000 })
    await replaceSearch.fill('M10 X 25 BLACK')
    const replacePatch = waitForCostLineStockPatch(page, stockB.id)
    await page
      .locator('[data-automation-id^="ItemSelect-option-"]')
      .filter({ hasText: stockB.description })
      .first()
      .click()
    await replacePatch

    await createAdjustmentFromNewRow(page, 'estimate', adjustmentDesc, '2', '-15', '-25')
    await createCostLineByApi(page, jobId, 'estimate', {
      kind: 'adjust',
      desc: deletedDesc,
      quantity: 1,
      unit_cost: 99,
      unit_rev: 99,
      accounting_date: accountingDate,
      ext_refs: {},
      meta: { source: 'e2e_delete_candidate' },
    })

    await navigateToCostTab(page, jobUrl, 'estimate')
    let adjustmentIndex = await waitForRowIndexByDescription(page, adjustmentDesc)

    const deletedIndex = await findRowIndexByDescription(page, deletedDesc)
    expect(deletedIndex).toBeGreaterThanOrEqual(0)
    await deleteRow(page, deletedIndex)

    await navigateToCostTab(page, jobUrl, 'estimate')
    await expectRowAbsent(page, deletedDesc)

    const finalCostSet = await fetchCostSet(page, jobId, 'estimate')
    const lines = finalCostSet.cost_lines
    const labour = findLine(lines, 'Workshop', 'time')
    const material = findLine(lines, stockB.description, 'material')
    const adjustment = findLine(lines, adjustmentDesc, 'adjust')

    expect(money(labour.quantity)).toBeCloseTo(Number(labourQuantity), 2)
    expect(money(labour.unit_cost)).toBeCloseTo(money(defaults.wage_rate), 2)
    expect(money(labour.unit_rev)).toBeCloseTo(money(workshopRate.charge_out_rate), 2)
    expect(money(material.quantity)).toBeCloseTo(10, 2)
    expect(material.ext_refs).toEqual(expect.objectContaining({ stock_id: stockB.id }))
    expect(money(material.unit_cost)).toBeCloseTo(money(stockB.unit_cost), 2)
    expect(money(material.unit_rev)).toBeCloseTo(money(stockB.unit_revenue), 2)
    expect(money(adjustment.quantity)).toBeCloseTo(2, 2)
    expect(money(adjustment.unit_cost)).toBeCloseTo(-15, 2)
    expect(money(adjustment.unit_rev)).toBeCloseTo(-25, 2)
    expect(lines.some((line) => line.desc === deletedDesc)).toBe(false)
    expectCostSetTotals([labour, material, adjustment])
    expect(sumCost(lines)).toBeCloseTo(expectedEstimateCost, 2)
    expect(sumRevenue(lines)).toBeCloseTo(expectedEstimateRevenue, 2)

    const labourIndexAfter = await findRowIndexByDescription(page, 'Workshop')
    materialIndex = await findRowIndexByDescription(page, stockB.description)
    adjustmentIndex = await findRowIndexByDescription(page, adjustmentDesc)
    await expect(autoId(page, `SmartCostLinesTable-quantity-${labourIndexAfter}`)).toHaveValue(
      labourQuantity,
    )
    await expect(autoId(page, `SmartCostLinesTable-quantity-${materialIndex}`)).toHaveValue('10')
    await expect(autoId(page, `SmartCostLinesTable-unit-rev-${adjustmentIndex}`)).toHaveValue('-25')
  })

  test('actual labour material adjustment and delete reconcile persisted costs', async ({
    authenticatedPage: page,
  }) => {
    const jobUrl = await createTestJob(page, 'ActualData')
    const jobId = getJobIdFromUrl(jobUrl)
    const defaults = await getCompanyDefaults(page)
    const me = await getMe(page)
    const workshopRate = await findWorkshopRate(page, jobId)
    const stock = await fetchStock(page, 'M8 ZINC', 'M8 ZINC WING NUT')
    const accountingDate = latestWeekdayDate()
    const labourDesc = `E2E actual labour ${Date.now()}`
    const adjustmentDesc = `E2E actual adjustment ${Date.now()}`
    const deletedDesc = `E2E actual deleted ${Date.now()}`
    const expectedActualMaterialUnitRev = roundMoney(
      money(stock.unit_cost) * (1 + money(defaults.materials_markup)),
    )

    const labourId = await createTimesheetLabourByApi(page, {
      jobId,
      staffId: me.id,
      labourSubtype: workshopRate.labour_subtype,
      date: accountingDate,
      hours: 1.25,
      description: labourDesc,
    })

    await navigateToCostTab(page, jobUrl, 'actual')

    const consumeResponse = waitForStockConsume(page)
    await selectItemFromNewRow(page, 'M8 ZINC', 'M8 ZINC WING NUT')
    await consumeResponse

    let materialIndex = await waitForRowIndexByDescription(page, stock.description)
    await editNumberCell(page, materialIndex, 'quantity', '2')

    await createAdjustmentFromNewRow(page, 'actual', adjustmentDesc, '3', '-12', '-18')
    await createCostLineByApi(page, jobId, 'actual', {
      kind: 'adjust',
      desc: deletedDesc,
      quantity: 1,
      unit_cost: 55,
      unit_rev: 55,
      accounting_date: accountingDate,
      ext_refs: {},
      meta: { source: 'e2e_delete_candidate' },
    })

    await navigateToCostTab(page, jobUrl, 'actual')
    let adjustmentIndex = await waitForRowIndexByDescription(page, adjustmentDesc)

    const deletedIndex = await findRowIndexByDescription(page, deletedDesc)
    expect(deletedIndex).toBeGreaterThanOrEqual(0)
    await deleteRow(page, deletedIndex)

    await navigateToCostTab(page, jobUrl, 'actual')
    await expectRowAbsent(page, deletedDesc)

    const finalCostSet = await fetchCostSet(page, jobId, 'actual')
    const lines = finalCostSet.cost_lines
    const labour = lines.find((line) => line.id === labourId)
    if (!labour) throw new Error(`Could not find actual labour line ${labourId}`)
    const material = findLine(lines, stock.description, 'material')
    const adjustment = findLine(lines, adjustmentDesc, 'adjust')
    const actualRevenue = lines.reduce((total, line) => total + money(line.total_rev), 0)
    const expectedActualCost =
      lineCost(1.25, money(labour.unit_cost)) +
      lineCost(2, money(stock.unit_cost)) +
      lineCost(3, -12)
    const expectedActualRevenue =
      lineRevenue(1.25, money(workshopRate.charge_out_rate)) +
      lineRevenue(2, expectedActualMaterialUnitRev) +
      lineRevenue(3, -18)

    expect(labour.kind).toBe('time')
    expect(labour.meta).toEqual(expect.objectContaining({ staff_id: me.id }))
    expect(money(labour.quantity)).toBeCloseTo(1.25, 2)
    // Wage coherence: the pricing pipeline stamped the wage it priced with,
    // and a x1 multiplier means unit cost IS that wage (see header deviations
    // for why the independent staff read is unavailable to this spec).
    expect(money(labour.unit_cost)).toBeGreaterThan(0)
    expect(money(labour.unit_cost)).toBeCloseTo(
      money((labour.meta ?? {}).wage_rate, 'labour meta wage_rate'),
      2,
    )
    expect(money(labour.unit_rev)).toBeCloseTo(money(workshopRate.charge_out_rate), 2)
    expect(material.approved).toBe(true)
    expect(material.ext_refs).toEqual(expect.objectContaining({ stock_id: stock.id }))
    expect(money(material.quantity)).toBeCloseTo(2, 2)
    expect(money(material.unit_cost)).toBeCloseTo(money(stock.unit_cost), 2)
    expect(money(material.unit_rev)).toBeCloseTo(expectedActualMaterialUnitRev, 2)
    expect(money(adjustment.quantity)).toBeCloseTo(3, 2)
    expect(money(adjustment.unit_cost)).toBeCloseTo(-12, 2)
    expect(money(adjustment.unit_rev)).toBeCloseTo(-18, 2)
    expect(lines.some((line) => line.desc === deletedDesc)).toBe(false)
    expectCostSetTotals([labour, material, adjustment])
    expect(sumCost(lines)).toBeCloseTo(expectedActualCost, 2)
    expect(sumRevenue(lines)).toBeCloseTo(expectedActualRevenue, 2)

    const timeExpensesText = await autoId(page, 'JobActualTab-time-expenses').textContent()
    const timeExpensesDigits = timeExpensesText?.match(/\$?([\d,]+\.?\d*)/)?.[1]
    if (!timeExpensesDigits) {
      throw new Error(
        `Could not parse Time & Expenses value from ${JSON.stringify(timeExpensesText)}`,
      )
    }
    const timeExpensesValue = money(timeExpensesDigits.replace(/,/g, ''), 'Time & Expenses')
    expect(timeExpensesValue).toBeCloseTo(actualRevenue, 2)

    materialIndex = await findRowIndexByDescription(page, stock.description)
    adjustmentIndex = await findRowIndexByDescription(page, adjustmentDesc)
    await expect(autoId(page, `SmartCostLinesTable-quantity-${materialIndex}`)).toHaveValue('2')
    await expect(autoId(page, `SmartCostLinesTable-unit-rev-${adjustmentIndex}`)).toHaveValue('-18')
  })

  test('actual description-first stock selection consumes once and strands no row', async ({
    authenticatedPage: page,
  }) => {
    // Business risk: description-first entry on the actual tab consumed no
    // stock and reached no server record, leaving the operator looking at a
    // row that existed only in the browser. Item-first entry (covered above)
    // always worked, which is why this went unnoticed.
    const jobUrl = await createTestJob(page, 'ActualDescFirst')
    const jobId = getJobIdFromUrl(jobUrl)
    const defaults = await getCompanyDefaults(page)
    const stock = await fetchStock(page, 'M8 ZINC', 'M8 ZINC WING NUT')
    const expectedUnitRev = roundMoney(
      money(stock.unit_cost) * (1 + money(defaults.materials_markup)),
    )

    await navigateToCostTab(page, jobUrl, 'actual')

    const rows = page.locator('[data-automation-id^="DataTable-row-"]')
    const trailingRow = rows.last()
    const draftRowId = await trailingRow.getAttribute('data-row-id')
    if (!draftRowId) throw new Error('Trailing cost row has no stable row ID')

    // Type a description first, promoting the phantom into a local draft.
    await trailingRow.locator('textarea').first().click()
    await page.keyboard.type(`E2E desc first ${Date.now()}`)
    const promotedRow = page.locator(`[data-row-id="${draftRowId}"]`)

    // Then pick the stock item for that same row.
    const consumeResponse = waitForStockConsume(page)
    await promotedRow.locator('[data-automation-id^="SmartCostLinesTable-item-"]').click()
    const search = page.getByPlaceholder('Search items by description, code, or type...')
    await search.waitFor({ timeout: 10000 })
    await search.fill('M8 ZINC')
    const option = page.locator('[data-automation-id^="ItemSelect-option-"]').filter({
      hasText: 'M8 ZINC WING NUT',
    })
    await option.first().waitFor({ timeout: 10000 })
    await option.first().click()
    await consumeResponse

    // A second row would mean the local draft outlived the row the consume
    // created.
    await navigateToCostTab(page, jobUrl, 'actual')
    await expect
      .poll(() => countRowsByDescription(page, stock.description), { timeout: 10000 })
      .toBe(1)

    const lines = (await fetchCostSet(page, jobId, 'actual')).cost_lines
    const material = findLine(lines, stock.description, 'material')
    expect(material.ext_refs).toEqual(expect.objectContaining({ stock_id: stock.id }))
    expect(money(material.quantity)).toBeCloseTo(1, 2)
    expect(money(material.unit_cost)).toBeCloseTo(money(stock.unit_cost), 2)
    expect(money(material.unit_rev)).toBeCloseTo(expectedUnitRev, 2)
    expect(lines.filter((line) => line.desc === stock.description)).toHaveLength(1)
  })
})
