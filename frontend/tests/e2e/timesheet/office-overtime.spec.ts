import { z } from 'zod'

import { getWorkshopStaff } from '../fixtures/api'
import { expect, test } from '../fixtures/auth'
import { autoId, createTestJob, getPhantomRowIndex } from '../helpers'
import {
  bookingDay,
  enterHours,
  isEntryWrite,
  openEntryViaDaily,
  readJobNumber,
  selectJobByNumber,
} from './support'

/**
 * The office grid asks the overtime question the worker's own screens ask:
 * the hours add up whoever enters them (owner, 2026-11-02).
 */
test('the office booking a day past the usual day is asked before it goes as overtime', async ({
  authenticatedPage: page,
}) => {
  const date = bookingDay('officeGridOvertime')
  await createTestJob(page, 'Office overtime')
  const jobNumber = await readJobNumber(page)
  const { id: staffId } = await getWorkshopStaff(page)
  const writes: string[] = []
  page.on('response', (response) => {
    if (isEntryWrite(response, 'POST')) writes.push(response.url())
  })

  await openEntryViaDaily(page, date)
  const rowIndex = await getPhantomRowIndex(page)
  await selectJobByNumber(page, rowIndex, jobNumber)
  await enterHours(page, rowIndex, '9h')

  // 9h on an empty day: the hour past the usual 8 is time and a half.
  const ask = autoId(page, 'TimesheetEntryPage-overtime')
  await expect(ask).toContainText('1h of this is past')
  await autoId(page, 'TimesheetEntryPage-overtime-cancel').click()
  await expect(ask).toBeHidden()
  // Cancelled: nothing saved, and the row stays as typed, not "failed".
  expect(writes).toEqual([])
  await expect(autoId(page, `SmartTimesheetTable-hours-${rowIndex}`)).toHaveValue('9h')
  await expect(page.locator(`[data-automation-id="DataTable-row-${rowIndex}"]`)).not.toContainText(
    'Save failed',
  )

  const created = page.waitForResponse((response) => isEntryWrite(response, 'POST'))
  await enterHours(page, rowIndex, '9h')
  await autoId(page, 'TimesheetEntryPage-overtime-save').click()
  expect((await created).ok()).toBe(true)

  const lineSchema = z.object({
    quantity: z.string(),
    meta: z.object({ wage_rate_multiplier: z.number() }),
  })
  await expect(async () => {
    const read = await page.request.get(
      `/api/job/timesheet/entries/?staff_id=${staffId}&date=${date}`,
    )
    const day = z.object({ cost_lines: z.array(lineSchema) }).parse(await read.json())
    expect(
      day.cost_lines.map((line) => [Number(line.quantity), line.meta.wage_rate_multiplier]),
    ).toEqual([
      [8, 1],
      [1, 1.5],
    ])
  }).toPass({ timeout: 15000 })
})
