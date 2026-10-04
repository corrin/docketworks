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

import { authenticateViaLoginPage, e2eCredentials, expect, test } from '../fixtures/auth'
import { getCompanyDefaults } from '../fixtures/api'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'
import { getLatestWeekdayDate, readJobNumber } from '../timesheet/support'

const TIMESHEETS_PATH = '/api/job/workshop/timesheets/'
const DRAWER = 'WorkshopTimesheetEntryDrawer'
const calendarEvent = (entryId: string) =>
  `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`

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
 * a week apart, which also keeps the working-day start the same.
 */
const PROJECT_WEEKS_BACK: Record<string, number> = { android: 0, iphone: 1 }
let date = ''

function projectDate(projectName: string): string {
  const weeksBack = PROJECT_WEEKS_BACK[projectName]
  if (weeksBack === undefined) throw new Error(`No booking day for project "${projectName}"`)
  return shiftDate(getLatestWeekdayDate(), -7 * weeksBack)
}

/**
 * The office user's part, in a desktop Chromium the spec launches itself for
 * both phone projects: creating a job is an office screen on an office
 * machine, so the phone browser only ever carries the workshop user's session.
 */
async function officeSetup(chromium: BrowserType, baseURL: string): Promise<OfficeSetup> {
  const browser = await chromium.launch()
  try {
    const context = await browser.newContext({ baseURL, viewport: { width: 1280, height: 720 } })
    const page = await context.newPage()
    const { username, password } = e2eCredentials('office')
    await authenticateViaLoginPage(page, username, password, () => () => undefined)

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
  } finally {
    await browser.close()
  }
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
  // Signing in ends with the app's own move to the board. Let that land
  // first: on WebKit a goto issued while it was still in flight was cut
  // across by it.
  if (new URL(page.url()).pathname.startsWith('/kanban')) {
    await expect(autoId(page, 'kanban-page')).toBeVisible()
  }
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

    await test.step('tapping 09:00 opens the drawer on that half hour', async () => {
      await tapCalendarSlot(page, '09:00:00')
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible()
      await expect(autoId(page, `${DRAWER}-start-time`)).toHaveValue('09:00')
      await expect(autoId(page, `${DRAWER}-end-time`)).toHaveValue('09:30')
      // iOS Safari zooms the page on focus when a field's text is under 16px.
      for (const field of ['start-time', 'end-time', 'rate', 'description']) {
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

    await test.step('saving puts the block on the calendar', async () => {
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

  test('a new entry defaults to the last job and the previous finish, and the chips move its times', async ({
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
      await expect(start).toHaveValue('09:30')
      await expect(end).toHaveValue('10:00')
      await expect(autoId(page, `${DRAWER}-rate`)).toHaveValue('1')
      await expect(autoId(page, `${DRAWER}-billable`)).toBeChecked()
    })

    await test.step('quick-adjust chips', async () => {
      await chip('plus-30').tap()
      await expect(end).toHaveValue('10:30')
      await chip('minus-5').tap()
      await expect(end).toHaveValue('10:25')
      await chip('plus-5').tap()
      await chip('plus-15').tap()
      await expect(end).toHaveValue('10:45')

      // Nothing of this user's starts after 09:30, so the gap runs to the
      // end of the day.
      await chip('fill-gap').tap()
      await expect(start).toHaveValue('09:30')
      await expect(end).toHaveValue('23:59')

      const defaults = await getCompanyDefaults(page)
      const weekday = new Date(`${date}T00:00:00`).getDay()
      const key = ['mon_start', 'tue_start', 'wed_start', 'thu_start', 'fri_start'][weekday - 1]
      const dayStart = z
        .string()
        .parse(key === undefined ? null : defaults[key])
        .slice(0, 5)
      await chip('reset').tap()
      await expect(start).toHaveValue(dayStart)
      await expect(end).toHaveValue(addMinutes(dayStart, 30))

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

  test('an entry without times lists below the calendar and is deleted there', async ({
    authenticatedPage: page,
  }, testInfo) => {
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
    const untimed = await savedEntry(seeded)

    await openMyTime(page)
    const row = page.locator(
      `[data-automation-id="WorkshopMyTimePage-untimed"] [data-event-id="${untimed.id}"]`,
    )
    await expect(row).toContainText(`#${setup.jobA.number}`)
    await expect(row).toContainText('2x')
    await expect(row).toContainText('Non-billable')
    await expect(row).toContainText('2h')
    await expectNoHorizontalOverflow(page)
    await attachScreenshot(page, testInfo, 'my-time-untimed')

    const destroy = timesheetWrite(page, 'DELETE')
    await autoId(page, `WorkshopMyTimePage-untimed-delete-${untimed.id}`).tap()
    expect((await destroy).ok()).toBe(true)
    await expect(page.getByText('Entry deleted.')).toBeVisible()
    await expect(row).toHaveCount(0)
  })
})
