/**
 * Workshop staff enter their own time on their phones. This drives the My
 * time page as the workshop login on the phone projects: add an entry by
 * tapping the calendar, pick the job inside the drawer, set the rate and the
 * billable tick, adjust times with the chips, move the entry to another job,
 * and delete it.
 *
 * The jobs are created through an office login in a desktop Chromium the
 * spec launches itself, because Create Job is an office control; everything
 * in the phone browser is the workshop user's own session.
 */
import type { APIResponse, BrowserType, Page, TestInfo } from '@playwright/test'
import { z } from 'zod'

import { shiftDate } from '../../../src/lib/dates'
import { formatHoursDisplay } from '../../../src/lib/format'

import { expect, test } from '../fixtures/auth'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'
import { getLatestWeekdayDate, readJobNumber } from '../timesheet/support'
import { asOffice, withCompanyAddress } from './support'

const TIMESHEETS_PATH = '/api/job/workshop/timesheets/'
const DRAWER = 'WorkshopTimesheetEntryDrawer'
const calendarEvent = (entryId: string) =>
  `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`

const daySchema = z.object({ default_entry_start: z.string() })
const placementSchema = z.object({ finish: z.string() })

const entrySchema = z.object({
  id: z.string(),
  job_id: z.string(),
  is_billable: z.boolean(),
  wage_rate_multiplier: z.number(),
  start_time: z.string().nullable(),
  end_time: z.string().nullable(),
})

interface TestJob {
  id: string
  number: number
}

interface OfficeSetup {
  jobA: TestJob
  jobB: TestJob
  /** An archived job the drawer's job list does not hold: only the picker's
      whole-table search reaches it. */
  searchOnlyJob: TestJob
  /** An entry the office user booked for themselves on the spec's date. */
  officeEntryId: string
}

/**
 * The day this project books on. The phone projects run one after the other
 * against the same database, so each takes its own weekday: the same weekday
 * a week apart, which also keeps the working-day start the same. Never today:
 * the clock spec clocks the workshop user in and out today, which puts his
 * paid breaks on it, and this spec counts the day's hours from nothing.
 */
const PROJECT_WEEKS_BACK: Record<string, number> = { android: 8, iphone: 9 }
let date = ''

function projectDate(projectName: string): string {
  const weeksBack = PROJECT_WEEKS_BACK[projectName]
  if (weeksBack === undefined) throw new Error(`No booking day for project "${projectName}"`)
  return shiftDate(getLatestWeekdayDate(), -7 * weeksBack)
}

async function officeSetup(chromium: BrowserType, baseURL: string): Promise<OfficeSetup> {
  return asOffice(chromium, baseURL, async (page) => {
    const createJob = async (label: string): Promise<TestJob> => {
      const url = await createTestJob(page, `Phone My Time ${label}`)
      return { id: getJobIdFromUrl(url), number: await readJobNumber(page) }
    }
    // The second job starts from the first job's page: the navbar's Create
    // Job link is on every office page.
    const jobA = await createJob('A')
    const jobB = await createJob('B')

    const listed = z
      .object({ jobs: z.array(z.object({ id: z.string() })) })
      .parse(await (await page.request.get('/api/timesheets/jobs/')).json())
    const archived = z
      .object({ jobs: z.array(z.object({ id: z.string(), job_number: z.number() })) })
      .parse(
        await (
          await page.request.get('/api/job/jobs/fetch-by-column/archived/?max_jobs=50')
        ).json(),
      )
    const listedIds = new Set(listed.jobs.map((job) => job.id))
    const unlisted = archived.jobs.find((job) => !listedIds.has(job.id))
    if (unlisted === undefined) {
      throw new Error('Every archived job is in the timesheet job list; nothing is search-only.')
    }
    const searchOnlyJob = { id: unlisted.id, number: unlisted.job_number }

    const response = await page.request.post(TIMESHEETS_PATH, {
      data: {
        job_id: jobA.id,
        accounting_date: date,
        hours: 1,
        start_time: '15:00:00',
        end_time: '16:00:00',
        description: 'Office entry the workshop user must not edit',
      },
    })
    if (!response.ok()) {
      throw new Error(`Office entry seed failed: ${response.status()} ${await response.text()}`)
    }
    return {
      jobA,
      jobB,
      searchOnlyJob,
      officeEntryId: entrySchema.parse(await response.json()).id,
    }
  })
}

function timesheetWrite(page: Page, method: 'POST' | 'PATCH' | 'DELETE') {
  return page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === TIMESHEETS_PATH &&
      response.request().method() === method,
  )
}

async function savedEntry(response: APIResponse | Awaited<ReturnType<typeof timesheetWrite>>) {
  if (!response.ok()) {
    throw new Error(`entry write answered ${response.status()}: ${await response.text()}`)
  }
  return entrySchema.parse(await response.json())
}

async function openMyTime(page: Page): Promise<void> {
  // Signing in ends with the app's own move to My time. Let that land first:
  // on WebKit a goto issued while it was still in flight was cut across by it.
  await expect(autoId(page, 'WorkshopTimesheetCalendar')).toBeVisible()
  await page.goto(`/timesheets/my-time?date=${date}`)
  await expect(autoId(page, 'WorkshopTimesheetCalendar')).toBeVisible()
}

async function pickJob(page: Page, job: TestJob): Promise<void> {
  await autoId(page, `${DRAWER}-job-picker-trigger`).tap()
  const search = autoId(page, `${DRAWER}-job-picker-search`)
  await expect(search).toBeVisible()
  await search.fill(String(job.number))
  await autoId(page, `${DRAWER}-job-picker-option-${job.number}`).tap()
  await expect(autoId(page, `${DRAWER}-job-picker-trigger`)).toContainText(`#${job.number}`)
}

async function attachScreenshot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await testInfo.attach(name, {
    body: await page.screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  })
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, 'the page must not scroll sideways on a phone').toBeLessThanOrEqual(0)
}

/** "HH:mm" plus minutes, capped at the day's last minute as the app caps it. */
function addMinutes(time: string, minutes: number): string {
  const [hours, mins] = time.split(':').map(Number)
  const total = Math.min((hours ?? 0) * 60 + (mins ?? 0) + minutes, 24 * 60 - 1)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

test.use({ loginRole: 'workshop' })

/** FullCalendar draws a column layer over the slot lanes and takes the tap
    there, working the time out from where it landed: so the tap is forced at
    the lane's position rather than waiting for the lane itself to be on top. */
async function tapCalendarSlot(page: Page, time: string): Promise<void> {
  await page
    .locator(`[data-automation-id="WorkshopTimesheetCalendar"] [data-time="${time}"]`)
    .last()
    .tap({ force: true })
}

async function openEntry(page: Page, entryId: string): Promise<void> {
  await page.locator(calendarEvent(entryId)).tap()
  await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible()
}

test.describe.serial('workshop time entry on a phone', () => {
  let setup: OfficeSetup
  let firstEntryId = ''
  let secondEntryId = ''

  test.beforeAll(async ({ playwright }, testInfo) => {
    date = projectDate(testInfo.project.name)
    const baseURL = testInfo.project.use.baseURL
    if (!baseURL) throw new Error('The phone projects need a baseURL for the office setup.')
    setup = await officeSetup(playwright.chromium, baseURL)
  })

  // ---- The essential path: add, edit, move, delete; totals; unapproved. ----

  test('adds an entry by tapping a slot and picking the job in the drawer', async ({
    authenticatedPage: page,
  }, testInfo) => {
    await openMyTime(page)
    await expect(autoId(page, 'WorkshopMyTimePage-empty-hint')).toBeVisible()
    await expect(autoId(page, 'WorkshopTimesheetSummaryCard-job-count')).toHaveText('0 jobs')
    await expectNoHorizontalOverflow(page)
    await attachScreenshot(page, testInfo, 'my-time-empty')

    // The drawer fetches the job list as it opens.
    const jobsResponse = page.waitForResponse(
      (response) => new URL(response.url()).pathname === '/api/timesheets/jobs/',
    )

    await test.step('tapping 09:00 opens the drawer starting there, asking how long', async () => {
      await tapCalendarSlot(page, '09:00:00')
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible()
      await expect(autoId(page, `${DRAWER}-start-time`)).toHaveValue('09:00')
      await expect(autoId(page, `${DRAWER}-end-time`)).toHaveValue('')
      await expect(autoId(page, `${DRAWER}-hours`)).toHaveValue('')
      await expect(autoId(page, `${DRAWER}-submit`)).toBeDisabled()
      // iOS Safari zooms the page on focus when a field's text is under 16px.
      for (const field of ['hours', 'start-time', 'end-time', 'rate', 'description']) {
        const fontPx = await autoId(page, `${DRAWER}-${field}`).evaluate((element) =>
          Number.parseFloat(getComputedStyle(element).fontSize),
        )
        expect(fontPx, `${field} font size`).toBeGreaterThanOrEqual(16)
      }
      await attachScreenshot(page, testInfo, 'drawer-new')
    })

    await test.step('the job picker lists the production job count and fits the phone', async () => {
      const listed = z
        .object({ jobs: z.array(z.unknown()) })
        .parse(await (await jobsResponse).json())
      await autoId(page, `${DRAWER}-job-picker-trigger`).tap()
      const search = autoId(page, `${DRAWER}-job-picker-search`)
      await expect(search).toBeVisible()
      const popover = await search.evaluate((input) => {
        const box = input.closest('[data-radix-popper-content-wrapper]')?.getBoundingClientRect()
        return box ? { left: Math.round(box.left), right: Math.round(box.right) } : null
      })
      testInfo.annotations.push({
        type: 'job picker',
        description: `popover ${JSON.stringify(popover)} in a ${page.viewportSize()?.width}px viewport; ${listed.jobs.length} jobs listed`,
      })
      await attachScreenshot(page, testInfo, 'job-picker-open')
      await search.fill(String(setup.jobA.number))
      await autoId(page, `${DRAWER}-job-picker-option-${setup.jobA.number}`).tap()
      await expect(autoId(page, `${DRAWER}-job-picker-trigger`)).toContainText(
        `#${setup.jobA.number}`,
      )
    })

    await test.step('half an hour from nine: the finish is worked out, and the block drawn', async () => {
      await autoId(page, `${DRAWER}-hours`).fill('0.5')
      await expect(autoId(page, `${DRAWER}-end-time`)).toHaveValue('09:30')
      await expect(autoId(page, `${DRAWER}-duration`)).toContainText('30m from 09:00 to 09:30')
      await autoId(page, `${DRAWER}-description`).fill('Phone entry one')
      const create = timesheetWrite(page, 'POST')
      await autoId(page, `${DRAWER}-submit`).tap()
      const entry = await savedEntry(await create)
      firstEntryId = entry.id
      expect(entry.is_billable).toBe(true)
      expect(entry.wage_rate_multiplier).toBe(1)

      await expect(page.getByText('Time saved.')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeHidden()
      await expect(page.locator(calendarEvent(firstEntryId))).toContainText(`#${setup.jobA.number}`)
      await expect(autoId(page, 'WorkshopTimesheetSummaryCard-total-hours')).toHaveText('30m')
      await expect(autoId(page, 'WorkshopTimesheetSummaryCard-job-count')).toHaveText('1 job')
      await expect(autoId(page, 'WorkshopMyTimePage-empty-hint')).toHaveCount(0)
      await attachScreenshot(page, testInfo, 'my-time-one-entry')
    })
  })

  test('editing the times changes the totals', async ({ authenticatedPage: page }) => {
    await openMyTime(page)
    await openEntry(page, firstEntryId)
    const end = autoId(page, `${DRAWER}-end-time`)
    await expect(end).toHaveValue('09:30')

    await end.fill('10:00')
    await expect(autoId(page, `${DRAWER}-duration`)).toContainText('1h')
    const update = timesheetWrite(page, 'PATCH')
    await autoId(page, `${DRAWER}-submit`).tap()
    const entry = await savedEntry(await update)
    expect(entry.end_time).toBe('10:00:00')

    await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden()
    await expect(autoId(page, 'WorkshopTimesheetSummaryCard-total-hours')).toHaveText('1h')
    await expect(autoId(page, 'WorkshopTimesheetSummaryCard-billable-hours')).toHaveText('1h')
  })

  test('moves the entry to another job', async ({ authenticatedPage: page }) => {
    await openMyTime(page)
    await openEntry(page, firstEntryId)

    await pickJob(page, setup.jobB)
    const update = timesheetWrite(page, 'PATCH')
    await autoId(page, `${DRAWER}-submit`).tap()
    const response = await update
    // The tick was not touched, so billability is not sent: on a move it is
    // the server's rule.
    expect(response.request().postDataJSON()).not.toHaveProperty('is_billable')
    const entry = await savedEntry(response)
    expect(entry.job_id).toBe(setup.jobB.id)
    expect(entry.is_billable).toBe(true)

    await expect(page.locator(calendarEvent(firstEntryId))).toContainText(`#${setup.jobB.number}`)
    await expect(autoId(page, 'WorkshopTimesheetSummaryCard-job-count')).toHaveText('1 job')
  })

  test('the entry arrives unapproved, for the office to approve', async ({
    authenticatedPage: page,
  }) => {
    const response = await page.request.get(`/api/job/jobs/${setup.jobB.id}/cost_sets/actual/`)
    expect(response.ok()).toBe(true)
    const costSet = z
      .object({ cost_lines: z.array(z.object({ id: z.string(), approved: z.boolean() })) })
      .parse(await response.json())
    const line = costSet.cost_lines.find((candidate) => candidate.id === firstEntryId)
    expect(line, 'the entry is a cost line on its job').toBeDefined()
    expect(line?.approved).toBe(false)
  })

  test("another person's entry is not shown and cannot be changed", async ({
    authenticatedPage: page,
  }) => {
    await openMyTime(page)
    await expect(page.locator(calendarEvent(firstEntryId))).toBeVisible()
    await expect(page.locator(calendarEvent(setup.officeEntryId))).toHaveCount(0)

    const patch = await page.request.patch(TIMESHEETS_PATH, {
      data: { entry_id: setup.officeEntryId, description: 'changed by someone else' },
    })
    expect(patch.status()).toBe(403)
    const destroy = await page.request.delete(`${TIMESHEETS_PATH}?entry_id=${setup.officeEntryId}`)
    expect(destroy.status()).toBe(403)
  })

  test('deletes the entry from the drawer', async ({ authenticatedPage: page }) => {
    await openMyTime(page)
    await openEntry(page, firstEntryId)

    const destroy = timesheetWrite(page, 'DELETE')
    await autoId(page, `${DRAWER}-delete`).tap()
    expect((await destroy).ok()).toBe(true)
    await expect(page.getByText('Entry deleted.')).toBeVisible()
    await expect(page.locator(calendarEvent(firstEntryId))).toHaveCount(0)
    await expect(autoId(page, 'WorkshopTimesheetSummaryCard-total-hours')).toHaveText('0h')
    await expect(autoId(page, 'WorkshopMyTimePage-empty-hint')).toBeVisible()
  })

  test("books against a job found only through the picker's search", async ({
    authenticatedPage: page,
  }) => {
    // An archived job is not in the list the drawer loads; typing its number
    // reaches it through the picker's whole-table search.
    await openMyTime(page)
    await autoId(page, 'WorkshopTimesheetSummaryCard-add').tap()
    await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible()

    await pickJob(page, setup.searchOnlyJob)
    const submit = autoId(page, `${DRAWER}-submit`)
    // Hours are the one thing a new entry must say.
    await expect(submit).toBeDisabled()
    await autoId(page, `${DRAWER}-hours`).fill('0.5')
    await expect(submit).toBeEnabled()
    const create = timesheetWrite(page, 'POST')
    await submit.tap()
    const entry = await savedEntry(await create)
    expect(entry.job_id).toBe(setup.searchOnlyJob.id)
    await expect(page.locator(calendarEvent(entry.id))).toContainText(
      `#${setup.searchOnlyJob.number}`,
    )

    // The later tests start from an empty day.
    const removed = await page.request.delete(`${TIMESHEETS_PATH}?entry_id=${entry.id}`)
    expect(removed.ok()).toBe(true)
  })

  // ---- Rate and billable, defaults, quick-adjust chips, untimed entries. ----

  test('a new entry defaults to the last job and the previous finish, and the chips move its finish', async ({
    authenticatedPage: page,
  }, testInfo) => {
    const earlier = await page.request.post(TIMESHEETS_PATH, {
      data: {
        job_id: setup.jobA.id,
        accounting_date: date,
        hours: 0.5,
        start_time: '09:00:00',
        end_time: '09:30:00',
        description: 'Earlier entry',
      },
    })
    await savedEntry(earlier)

    await openMyTime(page)
    await autoId(page, 'WorkshopTimesheetSummaryCard-add').tap()
    await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible()

    const start = autoId(page, `${DRAWER}-start-time`)
    const end = autoId(page, `${DRAWER}-end-time`)
    const chip = (id: string) => autoId(page, `${DRAWER}-chip-${id}`)

    await test.step('defaults', async () => {
      await expect(autoId(page, `${DRAWER}-job-picker-trigger`)).toContainText(
        `#${setup.jobA.number}`,
      )
      // After the last entry; the hours are his to say, so the finish waits.
      await expect(start).toHaveValue('09:30')
      await expect(end).toHaveValue('')
      await expect(autoId(page, `${DRAWER}-rate`)).toHaveValue('1')
      await expect(autoId(page, `${DRAWER}-billable`)).toBeChecked()
      // The chips move a finish, so they wait for one.
      await expect(chip('plus-30')).toBeDisabled()
    })

    await test.step('quick-adjust chips move the finish and the hours follow', async () => {
      await autoId(page, `${DRAWER}-hours`).fill('0.5')
      await expect(end).toHaveValue('10:00')
      await chip('plus-30').tap()
      await expect(end).toHaveValue('10:30')
      await expect(autoId(page, `${DRAWER}-hours`)).toHaveValue('1')
      await chip('minus-5').tap()
      await expect(end).toHaveValue('10:25')
      await chip('plus-5').tap()
      await chip('plus-15').tap()
      await expect(end).toHaveValue('10:45')
      await expect(autoId(page, `${DRAWER}-hours`)).toHaveValue('1.25')

      // Nothing of this user's starts after 09:30, so the gap runs to the end
      // of his day: nobody clocked this weekday, so the standard finish.
      const standardEnd = z
        .object({ standard: z.object({ end: z.string() }) })
        .parse(await (await page.request.get(`${TIMESHEETS_PATH}?date=${date}`)).json())
        .standard.end.slice(0, 5)
      await chip('fill-gap').tap()
      await expect(start).toHaveValue('09:30')
      await expect(end).toHaveValue(standardEnd)

      // Reset: back where the day is up to, half an hour long.
      await chip('reset').tap()
      await expect(start).toHaveValue('09:30')
      await expect(end).toHaveValue('10:00')

      await chip('now').tap()
      const nowStart = await start.inputValue()
      expect(nowStart).toMatch(/^\d{2}:\d{2}$/)
      await expect(end).toHaveValue(addMinutes(nowStart, 30))
      await attachScreenshot(page, testInfo, 'drawer-chips')
    })

    await test.step('time and a half, not billable', async () => {
      await start.fill('10:00')
      await end.fill('11:00')
      await expect(autoId(page, `${DRAWER}-duration`)).toContainText('1h')
      await autoId(page, `${DRAWER}-rate`).selectOption('1.5')
      await autoId(page, `${DRAWER}-billable`).tap()
      await expect(autoId(page, `${DRAWER}-billable`)).not.toBeChecked()
      await autoId(page, `${DRAWER}-description`).fill('Phone entry two')

      const create = timesheetWrite(page, 'POST')
      await autoId(page, `${DRAWER}-submit`).tap()
      const entry = await savedEntry(await create)
      secondEntryId = entry.id
      expect(entry.is_billable).toBe(false)
      expect(entry.wage_rate_multiplier).toBe(1.5)
    })

    await test.step('the totals follow', async () => {
      await expect(page.locator(calendarEvent(secondEntryId))).toBeVisible()
      await expect(autoId(page, 'WorkshopTimesheetSummaryCard-total-hours')).toHaveText('1h 30m')
      await expect(autoId(page, 'WorkshopTimesheetSummaryCard-billable-hours')).toHaveText('30m')
      await expect(autoId(page, 'WorkshopTimesheetSummaryCard-non-billable-hours')).toHaveText('1h')
      await attachScreenshot(page, testInfo, 'my-time-two-entries')
    })
  })

  test('moving an entry to another job keeps its rate and its unbillable choice', async ({
    authenticatedPage: page,
  }) => {
    await openMyTime(page)
    await openEntry(page, secondEntryId)
    await expect(autoId(page, `${DRAWER}-rate`)).toHaveValue('1.5')
    await expect(autoId(page, `${DRAWER}-billable`)).not.toBeChecked()

    await pickJob(page, setup.jobB)
    const update = timesheetWrite(page, 'PATCH')
    await autoId(page, `${DRAWER}-submit`).tap()
    const response = await update
    expect(response.request().postDataJSON()).not.toHaveProperty('is_billable')
    const entry = await savedEntry(response)
    expect(entry.job_id).toBe(setup.jobB.id)
    expect(entry.is_billable).toBe(false)
    expect(entry.wage_rate_multiplier).toBe(1.5)
    await expect(autoId(page, 'WorkshopTimesheetSummaryCard-job-count')).toHaveText('2 jobs')
  })

  test('hours saved without times are placed after his last entry, over the breaks', async ({
    authenticatedPage: page,
  }, testInfo) => {
    const day = daySchema.parse(
      await (await page.request.get(`${TIMESHEETS_PATH}?date=${date}`)).json(),
    )
    const placedFrom = day.default_entry_start
    const seeded = await page.request.post(TIMESHEETS_PATH, {
      data: {
        job_id: setup.jobA.id,
        accounting_date: date,
        hours: 2,
        description: 'Booked without times',
        wage_rate_multiplier: 2,
        is_billable: false,
      },
    })
    const placed = await savedEntry(seeded)
    // The server's one placement rule, asked the same question.
    const expected = placementSchema.parse(
      await (
        await page.request.get(
          `/api/timesheets/my-day/placement/?date=${date}&start=${placedFrom}&hours=2`,
        )
      ).json(),
    )

    expect([placed.start_time, placed.end_time]).toEqual([placedFrom, expected.finish])
    await openMyTime(page)
    const block = page.locator(calendarEvent(placed.id))
    await expect(block).toContainText(`#${setup.jobA.number}`)
    await expect(block).toContainText('2h')
    await expect(autoId(page, 'WorkshopMyTimePage-untimed')).toHaveCount(0)
    await attachScreenshot(page, testInfo, 'my-time-placed')

    await openEntry(page, placed.id)
    const destroy = timesheetWrite(page, 'DELETE')
    await autoId(page, `${DRAWER}-delete`).tap()
    expect((await destroy).ok()).toBe(true)
    await expect(page.getByText('Entry deleted.')).toBeVisible()
    await expect(block).toHaveCount(0)
  })

  // ---- Approval: what the worker sees before and after the office approves. ----

  test('an entry reads Waiting, then Approved and read-only once the office approves it', async ({
    authenticatedPage: page,
    playwright,
  }, testInfo) => {
    const weekHours = async () =>
      z
        .object({ week: z.object({ approved_hours: z.number(), waiting_hours: z.number() }) })
        .parse(await (await page.request.get(`${TIMESHEETS_PATH}?date=${date}`)).json()).week
    const before = await weekHours()
    const booked = await savedEntry(
      await page.request.post(TIMESHEETS_PATH, {
        data: {
          job_id: setup.jobA.id,
          accounting_date: date,
          hours: 1.5,
          start_time: '13:00:00',
          end_time: '14:30:00',
          description: 'Waiting for the office',
        },
      }),
    )
    // Booked today for an earlier day, so it is marked late.
    const block = page.locator(calendarEvent(booked.id))
    const weekWaiting = autoId(page, 'WorkshopTimesheetSummaryCard-week-waiting-hours')
    const weekApproved = autoId(page, 'WorkshopTimesheetSummaryCard-week-approved-hours')

    await openMyTime(page)
    await expect(block).toContainText('Waiting · Entered late')
    await expect(weekWaiting).toHaveText(formatHoursDisplay(before.waiting_hours + 1.5))
    await expect(weekApproved).toHaveText(formatHoursDisplay(before.approved_hours))
    await attachScreenshot(page, testInfo, 'my-time-waiting')

    const baseURL = z.string().parse(testInfo.project.use.baseURL)
    await asOffice(playwright.chromium, baseURL, async (office) => {
      const approval = await office.request.post(`/api/job/cost_lines/${booked.id}/approve/`)
      if (!approval.ok()) {
        throw new Error(`Approval answered ${approval.status()}: ${await approval.text()}`)
      }
    })

    await autoId(page, 'WorkshopTimesheetSummaryCard-refresh').tap()
    await expect(block).toContainText('Approved')
    await expect(weekWaiting).toHaveText(formatHoursDisplay(before.waiting_hours))
    await expect(weekApproved).toHaveText(formatHoursDisplay(before.approved_hours + 1.5))

    await test.step('the approved entry opens read-only', async () => {
      await block.tap()
      await expect(page.getByRole('heading', { name: 'Approved entry' })).toBeVisible()
      await expect(autoId(page, `${DRAWER}-locked`)).toBeVisible()
      await expect(autoId(page, `${DRAWER}-start-time`)).toBeDisabled()
      await expect(autoId(page, `${DRAWER}-description`)).toBeDisabled()
      await expect(autoId(page, `${DRAWER}-submit`)).toHaveCount(0)
      await expect(autoId(page, `${DRAWER}-delete`)).toHaveCount(0)
      await expectNoHorizontalOverflow(page)
      await attachScreenshot(page, testInfo, 'drawer-approved')
      await autoId(page, `${DRAWER}-cancel`).tap()
    })

    await test.step('and the server refuses a change to it', async () => {
      const patch = await page.request.patch(TIMESHEETS_PATH, {
        data: { entry_id: booked.id, description: 'changed after approval' },
      })
      expect(patch.status()).toBe(409)
      const destroy = await page.request.delete(`${TIMESHEETS_PATH}?entry_id=${booked.id}`)
      expect(destroy.status()).toBe(409)
    })
  })

  // ---- Remote entry: a save is marked unless the phone is at the company address. ----

  test('a save reads Suspicious remote entry unless the phone is at the company address', async ({
    authenticatedPage: page,
    context,
    playwright,
  }, testInfo) => {
    const baseURL = z.string().parse(testInfo.project.use.baseURL)
    const addFromThePhone = async (description: string) => {
      await autoId(page, 'WorkshopTimesheetSummaryCard-add').tap()
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible()
      await pickJob(page, setup.jobA)
      await autoId(page, `${DRAWER}-hours`).fill('0.5')
      await autoId(page, `${DRAWER}-description`).fill(description)
      const create = timesheetWrite(page, 'POST')
      await autoId(page, `${DRAWER}-submit`).tap()
      const entry = await savedEntry(await create)
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeHidden()
      return page.locator(`[data-event-id="${entry.id}"]`)
    }

    await withCompanyAddress(
      playwright.chromium,
      baseURL,
      page,
      async ({ atTheWorkshop, elsewhere }) => {
        await context.grantPermissions(['geolocation'])
        await context.setGeolocation(atTheWorkshop)
        // Loaded after the address is set: the page asks for location only when
        // the company has one.
        await openMyTime(page)
        const onSite = await addFromThePhone('Entered at the workshop')
        await expect(onSite).toContainText('Waiting')
        await expect(onSite).not.toContainText('Suspicious remote entry')

        await context.setGeolocation(elsewhere)
        const offSite = await addFromThePhone('Entered somewhere else')
        await expect(offSite).toContainText('Suspicious remote entry')

        await context.clearPermissions()
        const refused = await addFromThePhone('Entered with location refused')
        await expect(refused).toContainText('Suspicious remote entry')

        await expect(onSite).not.toContainText('Suspicious remote entry')
        await expectNoHorizontalOverflow(page)
        await attachScreenshot(page, testInfo, 'my-time-remote-entry')
      },
    )
  })
})
