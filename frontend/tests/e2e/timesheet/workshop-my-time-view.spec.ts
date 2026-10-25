import type { Page } from '@playwright/test'
import { z } from 'zod'

import { shiftDate } from '../../../src/lib/dates'
import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob } from '../helpers'
import { getLatestWeekdayDate, readJobNumber } from './support'

/**
 * The workshop "my time" calendar: day navigation, refresh, and the
 * add/update/delete round trip through the entry drawer.
 *
 * Port deviations from v1, each deliberate:
 * - The shared job is created by the first serial test through the standard
 *   authenticated fixture, not a hand-rolled beforeAll login.
 * - The job picker is the shared JobPicker popover, not v1's separate
 *   picker drawer, so selection goes trigger → search → option.
 * - There is no hours field: the drawer derives hours from the start/end
 *   pair (the server refuses a trio that disagrees).
 * - The calendar block must carry the id the create response returned —
 *   v1 only console.warned on a mismatch.
 */

const CALENDAR_EVENT = (entryId: string) =>
  `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`

async function openMyTimeView(page: Page): Promise<void> {
  await page.goto('/timesheets/my-time')
  await expect(page.getByText('Workshop timesheets')).toBeVisible({ timeout: 15000 })
  await autoId(page, 'WorkshopMyTimeHeader-date').waitFor({ timeout: 10000 })
}

function timesheetResponse(page: Page, method: 'GET' | 'POST' | 'PATCH' | 'DELETE') {
  return page.waitForResponse(
    (response) =>
      response.url().includes('/api/job/workshop/timesheets/') &&
      response.request().method() === method &&
      [200, 201, 204].includes(response.status()),
    { timeout: 15000 },
  )
}

/** A wire time ("HH:MM:SS") moved by some minutes, as the wire writes it. */
function clock(time: string, minutes: number): string {
  return new Date(
    Date.UTC(2000, 0, 1, Number(time.slice(0, 2)), Number(time.slice(3, 5)) + minutes),
  )
    .toISOString()
    .slice(11, 19)
}

async function selectJobInPicker(page: Page, jobNumber: number): Promise<void> {
  await autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker-trigger').click()
  const search = autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker-search')
  await expect(search).toBeVisible({ timeout: 10000 })
  await search.fill(String(jobNumber))
  const option = autoId(page, `WorkshopTimesheetEntryDrawer-job-picker-option-${jobNumber}`)
  await option.waitFor({ timeout: 10000 })
  await option.click()
}

test.describe.serial('workshop my time view', () => {
  let jobNumber = 0

  test('create the shared job', async ({ authenticatedPage: page }) => {
    await createTestJob(page, 'Workshop My Time')
    jobNumber = await readJobNumber(page)
  })

  test('moves between days', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)
    const dateBadge = autoId(page, 'WorkshopMyTimeHeader-date')
    const initialDate = (await dateBadge.textContent())?.trim() ?? ''
    expect(initialDate).not.toBe('')

    await test.step('move to previous day', async () => {
      await autoId(page, 'WorkshopMyTimeHeader-previous-day').click()
      await expect(dateBadge).not.toHaveText(initialDate)
    })

    await test.step('move to next day', async () => {
      await autoId(page, 'WorkshopMyTimeHeader-next-day').click()
      await expect(dateBadge).toHaveText(initialDate)
    })
  })

  test('refreshes a day', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)

    const refresh = timesheetResponse(page, 'GET')
    await autoId(page, 'WorkshopTimesheetSummaryCard-refresh').click()
    const response = await refresh
    expect(response.status()).toBe(200)
    await expect(autoId(page, 'WorkshopTimesheetSummaryCard-refresh')).toBeEnabled()
  })

  test('adds, updates, and deletes an entry', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)
    let entryId = ''

    await test.step('add a new entry via the drawer', async () => {
      await autoId(page, 'WorkshopTimesheetSummaryCard-add').click()
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible({
        timeout: 10000,
      })

      await selectJobInPicker(page, jobNumber)
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker-trigger')).toContainText(
        `#${jobNumber}`,
      )

      // Typed times give the hours: clear of the standard breaks, the whole span.
      await autoId(page, 'WorkshopTimesheetEntryDrawer-start-time').fill('09:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-end-time').fill('10:00')
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-duration')).toContainText(
        '1h from 09:00 to 10:00',
      )
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-hours')).toHaveValue('1')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-description').fill('Workshop test entry')

      const submit = autoId(page, 'WorkshopTimesheetEntryDrawer-submit')
      await expect(submit).toBeEnabled({ timeout: 10000 })
      const createResponse = timesheetResponse(page, 'POST')
      await submit.click()

      // One entry: 09:00-10:00 meets no break and ends before the usual finish.
      const [created] = z
        .tuple([z.object({ id: z.string() })])
        .parse(await (await createResponse).json())
      entryId = created.id

      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeHidden({
        timeout: 10000,
      })
      const eventBlock = page.locator(CALENDAR_EVENT(entryId))
      await expect(eventBlock).toBeVisible({ timeout: 15000 })
      await expect(eventBlock).toContainText(`#${jobNumber}`)
    })

    await test.step('update the entry', async () => {
      await page.locator(CALENDAR_EVENT(entryId)).click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })

      await autoId(page, 'WorkshopTimesheetEntryDrawer-end-time').fill('11:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-description').fill(
        'Workshop test entry updated',
      )

      const update = timesheetResponse(page, 'PATCH')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-submit').click()
      await update
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })

      await page.locator(CALENDAR_EVENT(entryId)).click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-description')).toHaveValue(
        'Workshop test entry updated',
      )
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-end-time')).toHaveValue('11:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-cancel').click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })
    })

    await test.step('delete the entry', async () => {
      await page.locator(CALENDAR_EVENT(entryId)).click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })

      const destroy = timesheetResponse(page, 'DELETE')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-delete').click()
      await destroy
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })
      await expect(page.locator(CALENDAR_EVENT(entryId))).toHaveCount(0)
    })
  })

  test('a task past the usual finish asks first, and a break put on work cuts it', async ({
    authenticatedPage: page,
  }) => {
    // A weekday of its own, well back: the day has usual hours whatever today is.
    const date = shiftDate(getLatestWeekdayDate(), -7 * 12)
    const dayPath = `/api/job/workshop/timesheets/?date=${date}`
    const daySchema = z.object({
      standard: z.object({ end: z.string() }),
      entries: z.array(
        z.object({
          id: z.string(),
          start_time: z.string(),
          end_time: z.string(),
          wage_rate_multiplier: z.number(),
        }),
      ),
      breaks: z.array(z.object({ id: z.string().nullable(), start: z.string() })),
    })
    const readDay = async () => daySchema.parse(await (await page.request.get(dayPath)).json())
    const spans = async () =>
      (await readDay()).entries
        .toSorted((first, second) => first.start_time.localeCompare(second.start_time))
        .map((entry) => [entry.start_time, entry.end_time, entry.wage_rate_multiplier])

    const times = await page.request.put('/api/timesheets/my-day/times/', {
      data: { date, clock_in: '07:00', clock_out: '20:00' },
    })
    expect(times.ok(), await times.text()).toBe(true)
    const usualFinish = (await readDay()).standard.end
    const start = clock(usualFinish, -60)

    await test.step('three hours from an hour before the finish asks about overtime', async () => {
      await page.goto(`/timesheets/my-time?date=${date}`)
      await autoId(page, 'WorkshopTimesheetSummaryCard-add').click()
      await selectJobInPicker(page, jobNumber)
      await autoId(page, 'WorkshopTimesheetEntryDrawer-start-time').fill(start.slice(0, 5))
      await autoId(page, 'WorkshopTimesheetEntryDrawer-hours').fill('3')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-submit').click()

      const ask = autoId(page, 'WorkshopTimesheetEntryDrawer-overtime')
      await expect(ask).toContainText(`2h past your usual finish of ${usualFinish.slice(0, 5)}`)
      const create = timesheetResponse(page, 'POST')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-overtime-save').click()
      await create

      expect(await spans()).toEqual([
        [start, usualFinish, 1],
        [usualFinish, clock(usualFinish, 120), 1.5],
      ])
    })

    await test.step('a break put on that work cuts it, and taking it away joins it', async () => {
      const breakStart = clock(start, 15)
      const added = await page.request.post('/api/timesheets/my-day/breaks/', {
        data: {
          date,
          start: breakStart.slice(0, 5),
          end: clock(start, 30).slice(0, 5),
          paid: true,
        },
      })
      expect(added.ok(), await added.text()).toBe(true)
      expect(await spans()).toEqual([
        [start, breakStart, 1],
        [clock(start, 30), usualFinish, 1],
        [usualFinish, clock(usualFinish, 120), 1.5],
      ])

      const taken = (await readDay()).breaks.find((each) => each.start === breakStart)
      if (taken === undefined || taken.id === null) throw new Error(`No break at ${breakStart}`)
      const removed = await page.request.delete(`/api/timesheets/my-day/breaks/${taken.id}/`)
      expect(removed.ok(), await removed.text()).toBe(true)
      expect(await spans()).toEqual([
        [start, usualFinish, 1],
        [usualFinish, clock(usualFinish, 120), 1.5],
      ])
    })
  })
})
