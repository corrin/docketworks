import type { Page } from '@playwright/test'
import { z } from 'zod'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob } from '../helpers'
import { bookingDay, readJobNumber } from './support'

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

      const body: unknown = await (await createResponse).json()
      if (
        typeof body !== 'object' ||
        body === null ||
        !('id' in body) ||
        typeof body.id !== 'string'
      ) {
        throw new Error('Create response carried no entry id.')
      }
      entryId = body.id

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

  test('a long day asks about overtime, and a break he adds never changes an entry', async ({
    authenticatedPage: page,
  }) => {
    // A weekday of its own, well back, with the company's usual 07:00-15:00
    // day and its standard breaks (owner, 2026-10-25: the first 8 hours are
    // ordinary, the rest time and a half).
    const date = bookingDay('myTimeLongDay')
    const dayPath = `/api/job/workshop/timesheets/?date=${date}`
    const daySchema = z.object({
      entries: z.array(
        z.object({
          id: z.string(),
          start_time: z.string().nullable(),
          end_time: z.string().nullable(),
          hours: z.number(),
          wage_rate_multiplier: z.number(),
        }),
      ),
    })
    const readDay = async () => daySchema.parse(await (await page.request.get(dayPath)).json())
    const entries = async () =>
      (await readDay()).entries
        .toSorted((first, second) =>
          (first.start_time ?? '').localeCompare(second.start_time ?? ''),
        )
        .map((entry) => [entry.start_time, entry.end_time, entry.hours, entry.wage_rate_multiplier])

    const times = await page.request.put('/api/timesheets/my-day/times/', {
      data: { date, clock_in: '07:00', clock_out: '17:00' },
    })
    expect(times.ok(), await times.text()).toBe(true)

    await test.step('07:00 to 17:00 on one job asks first, then is 8h and 1h overtime', async () => {
      await page.goto(`/timesheets/my-time?date=${date}`)
      await autoId(page, 'WorkshopTimesheetSummaryCard-add').click()
      await selectJobInPicker(page, jobNumber)
      await autoId(page, 'WorkshopTimesheetEntryDrawer-start-time').fill('07:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-end-time').fill('17:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-submit').click()

      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-overtime')).toContainText(
        'past your usual day',
      )
      const create = timesheetResponse(page, 'POST')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-overtime-save').click()
      await create

      // Nine hours on the job: the three breaks are not. Eight are ordinary.
      expect(await entries()).toEqual([
        ['07:00:00', '16:00:00', 8, 1],
        ['16:00:00', '17:00:00', 1, 1.5],
      ])
    })

    // A break is his to add or take off; it never changes an entry (owner,
    // 2026-10-25): if he worked through it, he edits the entry himself.
    await test.step('a break added inside the entry, then taken off, leaves it as entered', async () => {
      const added = await page.request.post('/api/timesheets/my-day/breaks/', {
        data: { date, start: '09:00', end: '09:15', paid: true },
      })
      expect(added.ok(), await added.text()).toBe(true)
      expect((await entries())[0]).toEqual(['07:00:00', '16:00:00', 8, 1])

      const day = z
        .object({ breaks: z.array(z.object({ id: z.string().nullable(), start: z.string() })) })
        .parse(await (await page.request.get(dayPath)).json())
      const taken = day.breaks.find((each) => each.start === '09:00:00')
      if (taken === undefined || taken.id === null) throw new Error('No break at 09:00')
      const removed = await page.request.delete(`/api/timesheets/my-day/breaks/${taken.id}/`)
      expect(removed.ok(), await removed.text()).toBe(true)
      expect((await entries())[0]).toEqual(['07:00:00', '16:00:00', 8, 1])
    })

    // The day is reused by the next run: what this test made goes.
    for (const entry of (await readDay()).entries) {
      const gone = await page.request.delete(`/api/job/workshop/timesheets/?entry_id=${entry.id}`)
      expect(gone.ok(), await gone.text()).toBe(true)
    }
  })

  test('he puts the rest of his day on General work, and an entry takes its time from it', async ({
    authenticatedPage: page,
  }) => {
    // Owner, 2026-10-26: anyone can sweep the rest of their day into General
    // work, and General work is the time on no job and no break, so it
    // shrinks round what he enters next. A weekday of its own, well back.
    const date = bookingDay('myTimeGeneralWork')
    const dayPath = `/api/job/workshop/timesheets/?date=${date}`
    const daySchema = z.object({
      entries: z.array(
        z.object({
          id: z.string(),
          job_name: z.string(),
          start_time: z.string().nullable(),
          end_time: z.string().nullable(),
          hours: z.number(),
        }),
      ),
    })
    const readDay = async () => daySchema.parse(await (await page.request.get(dayPath)).json())
    const spans = async (jobName: string) =>
      (await readDay()).entries
        .filter((entry) => entry.job_name === jobName)
        .map((entry) => [entry.start_time, entry.end_time, entry.hours])
        .toSorted((first, second) => String(first[0]).localeCompare(String(second[0])))

    const times = await page.request.put('/api/timesheets/my-day/times/', {
      data: { date, clock_in: '07:00', clock_out: '15:00' },
    })
    expect(times.ok(), await times.text()).toBe(true)

    await test.step('the rest of the day goes on General work', async () => {
      await page.goto(`/timesheets/my-time?date=${date}`)
      await autoId(page, 'DayCard-general-work').click()
      await expect(page.getByText('7h booked to General work.')).toBeVisible()
      await expect(autoId(page, 'DayCard-general-work-on')).toBeVisible()
      expect(await spans('General work')).toEqual([
        ['07:00:00', '08:30:00', 1.5],
        ['08:45:00', '11:30:00', 2.75],
        ['12:00:00', '13:30:00', 1.5],
        ['13:45:00', '15:00:00', 1.25],
      ])
    })

    await test.step('2h on a job, no times typed, goes in from 07:00', async () => {
      await autoId(page, 'WorkshopTimesheetSummaryCard-add').click()
      await selectJobInPicker(page, jobNumber)
      await autoId(page, 'WorkshopTimesheetEntryDrawer-hours').fill('2')
      const create = timesheetResponse(page, 'POST')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-submit').click()
      await create

      const job = (await readDay()).entries.find((entry) => entry.job_name !== 'General work')
      if (job === undefined) throw new Error('No job entry saved')
      expect([job.start_time, job.end_time, job.hours]).toEqual(['07:00:00', '09:15:00', 2])
      expect(await spans('General work')).toEqual([
        ['09:15:00', '11:30:00', 2.25],
        ['12:00:00', '13:30:00', 1.5],
        ['13:45:00', '15:00:00', 1.25],
      ])
    })

    // The day is reused by the next run: what this test made goes. Deleting
    // one General work line takes the day's fill off, all of it; deleting an
    // entry first would rebuild it under new ids. So General work goes first.
    const remove = async (entryId: string) => {
      const gone = await page.request.delete(`/api/job/workshop/timesheets/?entry_id=${entryId}`)
      expect(gone.ok(), await gone.text()).toBe(true)
    }
    const generalWork = (await readDay()).entries.find((entry) => entry.job_name === 'General work')
    if (generalWork !== undefined) await remove(generalWork.id)
    for (const entry of (await readDay()).entries) await remove(entry.id)
  })
})
