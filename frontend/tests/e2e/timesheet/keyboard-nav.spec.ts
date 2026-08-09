import type { Page, Response } from '@playwright/test'
import { z } from 'zod'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getPhantomRowIndex } from '../helpers'
import { getTimesheetJobs, getTimesheetStaff, type TimesheetJob } from '../fixtures/api'
import { getLatestWeekdayDate, waitForEntryGrid } from './support'

/**
 * The keyboard-only entry flow: after ONE mouse click on the first picker,
 * two complete rows enter via Tab alone — search commits the highlighted
 * job, hours and description chain by Tab, the row-exit Tab fires the POST,
 * the next phantom's picker is disabled while the create is in flight, and
 * focus lands in the fresh phantom's search once it settles.
 *
 * Port deviation from v1: the two jobs are created by the first serial test
 * through the standard fixture (v1 used a hand-rolled beforeAll login).
 */

const createdLineSchema = z.object({
  entry_seq: z.number(),
  desc: z.string().nullable(),
  quantity: z.string(),
  total_cost: z.number(),
  total_rev: z.number(),
  labour_subtype: z.string().nullable(),
  meta: z.record(z.string(), z.unknown()),
})

interface CreatedLine {
  entry_seq: number
  desc: string
  quantity: number
  total_cost: number
  total_rev: number
  labour_subtype: string | null
  meta: Record<string, unknown>
}

async function parseCreated(response: Response): Promise<CreatedLine> {
  const body = createdLineSchema.parse(await response.json())
  return { ...body, desc: body.desc ?? '', quantity: Number(body.quantity) }
}

function expectCreatedCostLine(
  line: CreatedLine,
  expected: {
    entrySeq: number
    desc: string
    hours: number
    wageRate: number
    job: TimesheetJob
    staffId: string
  },
): void {
  expect(line.entry_seq).toBe(expected.entrySeq)
  expect(line.desc).toBe(expected.desc)
  expect(line.quantity).toBeCloseTo(expected.hours, 2)
  expect(line.total_cost).toBeCloseTo(expected.hours * expected.wageRate, 1)
  expect(line.labour_subtype).toBeTruthy()
  const rate = expected.job.labour_rates.find(
    (candidate) => candidate.labour_subtype === line.labour_subtype,
  )
  expect(rate, `labour_subtype ${line.labour_subtype} must be one of the job's rates`).toBeTruthy()
  expect(line.total_rev).toBeCloseTo(expected.hours * Number(rate!.charge_out_rate), 1)
  expect(line.meta.staff_id).toBe(expected.staffId)
}

async function assertRow(
  page: Page,
  seq: number,
  expected: { jobNumber: number; hoursText: string; desc: string; wage: number; bill: number },
): Promise<void> {
  const row = page.locator(`tr:has([data-entry-seq="${seq}"])`)
  await expect(row.locator('[data-automation-id$="-trigger"]')).toHaveText(
    new RegExp(`#${expected.jobNumber}`),
  )
  await expect(row.locator('[data-automation-id^="SmartTimesheetTable-hours-"]')).toHaveValue(
    expected.hoursText,
  )
  await expect(row.locator('[data-automation-id^="SmartTimesheetTable-description-"]')).toHaveValue(
    expected.desc,
  )
  const wageText =
    (await row.locator('[data-automation-id^="SmartTimesheetTable-wage-"]').textContent()) ?? ''
  const wage = Number(/\$?([\d,]+\.?\d*)/.exec(wageText)?.[1]?.replace(/,/g, ''))
  expect(wage).toBeCloseTo(expected.wage, 1)
  const billText =
    (await row.locator('[data-automation-id^="SmartTimesheetTable-bill-"]').textContent()) ?? ''
  const bill = Number(/\$?([\d,]+\.?\d*)/.exec(billText)?.[1]?.replace(/,/g, ''))
  expect(bill).toBeCloseTo(expected.bill, 1)
}

test.describe.serial('keyboard Tab entry flow', () => {
  let jobNumber1 = 0
  let jobNumber2 = 0

  test('create the two shared jobs', async ({ authenticatedPage: page }) => {
    await createTestJob(page, 'KbdNav-1')
    jobNumber1 = Number(
      /#(\d+)/.exec(await autoId(page, 'JobView-job-number').first().innerText())?.[1],
    )
    await createTestJob(page, 'KbdNav-2')
    jobNumber2 = Number(
      /#(\d+)/.exec(await autoId(page, 'JobView-job-number').first().innerText())?.[1],
    )
    expect(jobNumber1).toBeGreaterThan(0)
    expect(jobNumber2).toBeGreaterThan(0)
  })

  test('two rows enter keyboard-only with exact wire and display state', async ({
    authenticatedPage: page,
  }) => {
    const date = getLatestWeekdayDate()
    const staffList = await getTimesheetStaff(page, date)
    expect(staffList.length).toBeGreaterThan(0)
    const staff = staffList[0]!
    const staffWageRate = Number(staff.wageRate)
    expect(Number.isFinite(staffWageRate)).toBe(true)

    const jobs = await getTimesheetJobs(page)
    const job1 = jobs.find((candidate) => candidate.job_number === jobNumber1)
    const job2 = jobs.find((candidate) => candidate.job_number === jobNumber2)
    if (!job1 || !job2) throw new Error('Created jobs are not in the timesheet job list')
    expect(job1.labour_rates.length).toBeGreaterThan(0)
    expect(job2.labour_rates.length).toBeGreaterThan(0)

    // Delay the FIRST create so the in-flight disabled state is observable.
    let delayed = false
    await page.route(/\/cost_lines\/?$/, async (route) => {
      if (!delayed && route.request().method() === 'POST') {
        delayed = true
        await page.waitForTimeout(700)
      }
      await route.continue()
    })

    await page.goto(`/timesheets/entry?date=${date}&staffId=${staff.id}`)
    await waitForEntryGrid(page)
    const r0 = await getPhantomRowIndex(page)
    const r1 = r0 + 1
    const firstSeq = r0 + 1
    const secondSeq = firstSeq + 1

    // Row 1 — the single allowed mouse action is this trigger click.
    await autoId(page, `SmartTimesheetTable-jobPicker-${r0}-trigger`).click()
    const row1Search = autoId(page, `SmartTimesheetTable-jobPicker-${r0}-search`)
    await expect(row1Search).toBeFocused({ timeout: 3000 })
    await row1Search.pressSequentially(String(jobNumber1), { delay: 10 })
    await expect(
      autoId(page, `SmartTimesheetTable-jobPicker-${r0}-option-${jobNumber1}`),
    ).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-jobPicker-${r0}-trigger`)).toHaveText(
      new RegExp(`#${jobNumber1}`),
    )
    await expect(autoId(page, `SmartTimesheetTable-hours-${r0}`)).toBeFocused({ timeout: 3000 })
    await page.keyboard.type('2')
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-description-${r0}`)).toBeFocused({
      timeout: 3000,
    })
    await page.keyboard.type('Cutting')
    const firstPost = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await page.keyboard.press('Tab')

    // While the delayed POST is in flight the next phantom's picker locks.
    const nextTrigger = autoId(page, `SmartTimesheetTable-jobPicker-${r1}-trigger`)
    await nextTrigger.waitFor({ timeout: 3000 })
    await expect(nextTrigger).toBeDisabled({ timeout: 3000 })

    const row1Body = await parseCreated(await firstPost)
    expectCreatedCostLine(row1Body, {
      entrySeq: firstSeq,
      desc: 'Cutting',
      hours: 2,
      wageRate: staffWageRate,
      job: job1,
      staffId: staff.id,
    })

    await expect(autoId(page, `SmartTimesheetTable-jobPicker-${r1}-trigger`)).toBeEnabled({
      timeout: 5000,
    })
    const row2Search = autoId(page, `SmartTimesheetTable-jobPicker-${r1}-search`)
    await expect(row2Search).toBeFocused({ timeout: 5000 })

    await test.step('row 1 rendered from backend response', async () => {
      await assertRow(page, firstSeq, {
        jobNumber: jobNumber1,
        hoursText: '2h',
        desc: 'Cutting',
        wage: 2 * staffWageRate,
        bill: row1Body.total_rev,
      })
    })

    // Row 2 — keyboard continues without another click.
    await row2Search.pressSequentially(String(jobNumber2), { delay: 10 })
    await expect(
      autoId(page, `SmartTimesheetTable-jobPicker-${r1}-option-${jobNumber2}`),
    ).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-jobPicker-${r1}-trigger`)).toHaveText(
      new RegExp(`#${jobNumber2}`),
    )
    await expect(autoId(page, `SmartTimesheetTable-hours-${r1}`)).toBeFocused({ timeout: 3000 })
    await page.keyboard.type('3.5')
    await page.keyboard.press('Tab')
    await expect(autoId(page, `SmartTimesheetTable-description-${r1}`)).toBeFocused({
      timeout: 3000,
    })
    await page.keyboard.type('Welding')
    const secondPost = page.waitForResponse(
      (response) =>
        response.url().includes('/cost_lines/') && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await page.keyboard.press('Tab')
    const row2Body = await parseCreated(await secondPost)
    expectCreatedCostLine(row2Body, {
      entrySeq: secondSeq,
      desc: 'Welding',
      hours: 3.5,
      wageRate: staffWageRate,
      job: job2,
      staffId: staff.id,
    })

    await page.waitForLoadState('networkidle')
    await assertRow(page, firstSeq, {
      jobNumber: jobNumber1,
      hoursText: '2h',
      desc: 'Cutting',
      wage: 2 * staffWageRate,
      bill: row1Body.total_rev,
    })
    await assertRow(page, secondSeq, {
      jobNumber: jobNumber2,
      hoursText: '3h 30m',
      desc: 'Welding',
      wage: 3.5 * staffWageRate,
      bill: row2Body.total_rev,
    })
  })
})
