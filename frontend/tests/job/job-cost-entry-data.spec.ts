import { test, expect } from '../fixtures/auth'
import type { Page, Response } from '@playwright/test'
import { autoId, createTestJob } from '../fixtures/helpers'
import { getCompanyDefaults, getJobLabourRates, getStaffList } from '../fixtures/api'
import { getLatestWeekdayDate } from '../../src/utils/dateUtils'

type CostLine = {
  id: string
  kind: 'material' | 'time' | 'adjust'
  desc: string
  quantity: number | string
  unit_cost: number | string
  unit_rev: number | string
  total_cost: number | string
  total_rev: number | string
  approved?: boolean
  ext_refs?: Record<string, unknown>
  meta?: Record<string, unknown>
}

type CostSet = {
  cost_lines: CostLine[]
}

type StockItem = {
  id: string
  item_code: string | null
  description: string
  unit_cost: number | string
  unit_revenue: number | string
}

type XeroPayItem = {
  id: string
  name: string
  uses_leave_api: boolean
  multiplier?: number | null
}

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

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) throw new Error(`Unable to parse job id from url: ${url}`)
  return match[1]
}

async function navigateToCostTab(
  page: Page,
  jobUrl: string,
  tab: 'estimate' | 'quote' | 'actual',
): Promise<void> {
  await page.goto(`${jobUrl.split('?')[0]}?tab=${tab}`)
  await page.waitForLoadState('networkidle')
  await autoId(page, `JobViewTabs-${tab}`).click()
  await page.waitForLoadState('networkidle')
  await page.locator('[data-row-id]').last().waitFor({ timeout: 10000 })
}

async function fetchCostSet(page: Page, jobId: string, kind: 'estimate' | 'quote' | 'actual') {
  const response = await page.request.get(`/api/job/jobs/${jobId}/cost_sets/${kind}/`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as CostSet
}

async function fetchStock(page: Page, query: string, predicate?: (item: StockItem) => boolean) {
  const response = await page.request.get(
    `/api/purchasing/stock/search/?q=${encodeURIComponent(query)}&page=1&page_size=50`,
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { results: StockItem[] }
  const item = body.results.find(predicate ?? (() => true))
  if (!item) throw new Error(`No stock item found for query "${query}"`)
  return item
}

async function fetchOrdinaryPayItem(page: Page): Promise<XeroPayItem> {
  const response = await page.request.get('/api/workflow/xero-pay-items/')
  expect(response.ok()).toBe(true)
  const items = (await response.json()) as XeroPayItem[]
  const ordinary =
    items.find((item) => item.name === 'Ordinary Time' && !item.uses_leave_api) ??
    items.find(
      (item) =>
        !item.uses_leave_api &&
        item.multiplier !== null &&
        item.multiplier !== undefined &&
        money(item.multiplier, `Xero pay item multiplier for ${item.name}`) === 1,
    )
  if (!ordinary) throw new Error('No ordinary-time Xero pay item found')
  return ordinary
}

async function createCostLineByApi(
  page: Page,
  jobId: string,
  kind: 'estimate' | 'actual',
  payload: Partial<CostLine> & { accounting_date: string },
): Promise<CostLine> {
  const response = await page.request.post(`/api/job/jobs/${jobId}/cost_sets/${kind}/cost_lines/`, {
    data: payload,
  })
  expect(response.ok()).toBe(true)
  return (await response.json()) as CostLine
}

async function createTimesheetLabourByApi(
  page: Page,
  payload: {
    jobId: string
    staffId: string
    payItemId: string
    date: string
    hours: number
    description: string
  },
): Promise<string> {
  const response = await page.request.post('/api/job/timesheet/entries/', {
    data: {
      job_id: payload.jobId,
      staff_id: payload.staffId,
      xero_pay_item_id: payload.payItemId,
      date: payload.date,
      hours: payload.hours,
      description: payload.description,
      is_billable: true,
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { cost_line_id?: string }
  if (!body.cost_line_id) throw new Error('Timesheet create did not return cost_line_id')
  return body.cost_line_id
}

async function clickAddRow(page: Page): Promise<void> {
  const selectItemButton = page.getByRole('button', { name: 'Select Item' }).last()
  await selectItemButton.waitFor({ timeout: 5000 })
  await selectItemButton.click()
}

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

async function expectRowAbsent(page: Page, description: string): Promise<void> {
  expect(await findRowIndexByDescription(page, description)).toBe(-1)
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

    const body = res.request().postDataJSON() as { ext_refs?: { stock_id?: string } } | null
    return body?.ext_refs?.stock_id === stockId
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

async function createAdjustmentFromNewRow(
  page: Page,
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
  const trailingDescription = trailingRow.locator('[data-grid-col="desc"]')

  await trailingDescription.click()
  await page.keyboard.type(description)
  // Business risk: promoting the phantom with a different row identity replaces the textarea
  // after its first character, moving focus and truncating normal keyboard input.
  const promotedRow = page.locator(`[data-row-id="${draftRowId}"]`)
  const promotedDescription = promotedRow.locator('[data-grid-col="desc"]')
  await expect(promotedDescription).toBeFocused()
  await expect(promotedDescription).toHaveValue(description)
  await promotedDescription.press('Tab')

  // Business risk: API-seeded adjustments bypass the phantom-row promotion that keeps entry
  // continuous, so they allowed this user-visible regression to pass unnoticed.
  await expect(rows).toHaveCount(initialRowCount + 1)
  await expect(rows.last().locator('[data-grid-col="desc"]')).toHaveValue('')

  const quantityInput = promotedRow.locator('[data-grid-col="quantity"]')
  await quantityInput.fill(quantity)
  await quantityInput.press('Tab')

  const createResponse = waitForAnyCostLineCreate(page)
  const unitCostInput = promotedRow.locator('[data-grid-col="unit_cost"]')
  await unitCostInput.fill(unitCost)
  await unitCostInput.press('Tab')

  // Business risk: a fast keyboard user reaches Unit Revenue before the create response.
  // Waiting for POST here would hide stale-response data loss in the draft lifecycle.
  const unitRevenueInput = promotedRow.locator('[data-grid-col="unit_rev"]')
  await unitRevenueInput.fill(unitRevenue)
  await unitRevenueInput.press('Tab')

  const response = await createResponse
  const responseBody = await response.text()
  expect(response.status(), responseBody).toBe(expectedStatus)
  return draftRowId
}

async function deleteRow(page: Page, rowIndex: number): Promise<void> {
  page.once('dialog', (dialog) => dialog.accept())
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

test.describe('job cost entry data-first scenarios', () => {
  test.describe('quote draft failure', () => {
    test.use({
      expectedConsoleErrors: [
        'Failed to load resource: the server responded with a status of 503',
        'Failed to create cost line: AxiosError: Request failed with status code 503',
      ],
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
      await discardedRow.locator('[data-grid-col="desc"]').fill(discardedDesc)
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
        adjustmentDesc,
        '4',
        '-11',
        '-17',
        503,
      )
      await page.unroute(createUrl)

      const failedRow = page.locator(`[data-row-id="${failedDraftId}"]`)
      await expect(failedRow).toContainText('Save failed')
      const retryResponse = waitForAnyCostLineCreate(page)
      await failedRow.locator('[data-grid-col="unit_rev"]').focus()
      await failedRow.locator('[data-grid-col="unit_rev"]').press('Tab')
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
    // Labour revenue comes from the job's per-subtype rate, not company defaults
    const labourRates = await getJobLabourRates(page, jobId)
    const workshopRate = labourRates.find((rate) => rate.is_workshop)
    if (!workshopRate) throw new Error('Job has no workshop labour rate')
    const stockA = await fetchStock(page, 'M8 ZINC WING NUT', (item) =>
      item.description.includes('M8 ZINC WING NUT'),
    )
    const stockB = await fetchStock(page, 'M10 X 25 BLACK', (item) =>
      item.description.includes('M10 X 25 BLACK'),
    )
    const accountingDate = getLatestWeekdayDate()

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

    let labourIndex = await findRowIndexByDescription(page, 'Workshop')
    expect(labourIndex).toBeGreaterThanOrEqual(0)
    await editNumberCell(page, labourIndex, 'quantity', labourQuantity)

    const materialCreate = waitForCostLineCreate(page)
    await selectItemFromNewRow(page, 'M8 ZINC', 'M8 ZINC WING NUT')
    await materialCreate

    let materialIndex = await findRowIndexByDescription(page, stockA.description)
    expect(materialIndex).toBeGreaterThanOrEqual(0)
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

    await createAdjustmentFromNewRow(page, adjustmentDesc, '2', '-15', '-25')
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
    let adjustmentIndex = await findRowIndexByDescription(page, adjustmentDesc)
    expect(adjustmentIndex).toBeGreaterThanOrEqual(0)

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

    labourIndex = await findRowIndexByDescription(page, 'Workshop')
    materialIndex = await findRowIndexByDescription(page, stockB.description)
    adjustmentIndex = await findRowIndexByDescription(page, adjustmentDesc)
    await expect(autoId(page, `SmartCostLinesTable-quantity-${labourIndex}`)).toHaveValue(
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
    const staffList = await getStaffList(page)
    const staff = staffList.find(
      (candidate: { id: string; date_left: string | null; wage_rate: number }) =>
        !candidate.date_left && money(candidate.wage_rate, `staff ${candidate.id} wage_rate`) > 0,
    )
    if (!staff) throw new Error('No active staff with wage_rate found')
    const labourRates = await getJobLabourRates(page, jobId)
    const workshopRate = labourRates.find((rate) => rate.is_workshop)
    if (!workshopRate) throw new Error('Job has no workshop labour rate')
    const ordinaryPayItem = await fetchOrdinaryPayItem(page)
    const stock = await fetchStock(page, 'M8 ZINC WING NUT', (item) =>
      item.description.includes('M8 ZINC WING NUT'),
    )
    const accountingDate = getLatestWeekdayDate()
    const labourDesc = `E2E actual labour ${Date.now()}`
    const adjustmentDesc = `E2E actual adjustment ${Date.now()}`
    const deletedDesc = `E2E actual deleted ${Date.now()}`
    const expectedActualMaterialUnitRev = roundMoney(
      money(stock.unit_cost) * (1 + money(defaults.materials_markup)),
    )
    const expectedActualCost =
      lineCost(1.25, money(staff.wage_rate)) +
      lineCost(2, money(stock.unit_cost)) +
      lineCost(3, -12)
    const expectedActualRevenue =
      lineRevenue(1.25, money(workshopRate.charge_out_rate)) +
      lineRevenue(2, expectedActualMaterialUnitRev) +
      lineRevenue(3, -18)

    const labourId = await createTimesheetLabourByApi(page, {
      jobId,
      staffId: staff.id,
      payItemId: ordinaryPayItem.id,
      date: accountingDate,
      hours: 1.25,
      description: labourDesc,
    })

    await navigateToCostTab(page, jobUrl, 'actual')

    const consumeResponse = waitForStockConsume(page)
    await selectItemFromNewRow(page, 'M8 ZINC', 'M8 ZINC WING NUT')
    await consumeResponse

    let materialIndex = await findRowIndexByDescription(page, stock.description)
    expect(materialIndex).toBeGreaterThanOrEqual(0)
    await editNumberCell(page, materialIndex, 'quantity', '2')

    await createAdjustmentFromNewRow(page, adjustmentDesc, '3', '-12', '-18')
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
    let adjustmentIndex = await findRowIndexByDescription(page, adjustmentDesc)
    expect(adjustmentIndex).toBeGreaterThanOrEqual(0)

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

    expect(labour.kind).toBe('time')
    expect(labour.meta).toEqual(expect.objectContaining({ staff_id: staff.id }))
    expect(money(labour.quantity)).toBeCloseTo(1.25, 2)
    expect(money(labour.unit_cost)).toBeCloseTo(money(staff.wage_rate), 2)
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
    const timeExpensesMatch = timeExpensesText?.match(/\$?([\d,]+\.?\d*)/)
    if (!timeExpensesMatch) {
      throw new Error(
        `Could not parse Time & Expenses value from ${JSON.stringify(timeExpensesText)}`,
      )
    }
    const timeExpensesValue = money(timeExpensesMatch[1].replace(/,/g, ''), 'Time & Expenses')
    expect(timeExpensesValue).toBeCloseTo(actualRevenue, 2)

    materialIndex = await findRowIndexByDescription(page, stock.description)
    adjustmentIndex = await findRowIndexByDescription(page, adjustmentDesc)
    await expect(autoId(page, `SmartCostLinesTable-quantity-${materialIndex}`)).toHaveValue('2')
    await expect(autoId(page, `SmartCostLinesTable-unit-rev-${adjustmentIndex}`)).toHaveValue('-18')
  })
})
