/**
 * Filling and sending a day on a phone (KAN-376). The owner's test: today the
 * worker "has to do all the arithmetic to ensure it adds up to 8 hours", and
 * this has to be materially better for him. So the spec asserts what he is
 * told (the day as a timeline with its breaks, and "8h to fill") and counts
 * what it costs him: the taps to record a three-job day.
 *
 * Each phone project works on its own past weekday, clear of the other phone
 * specs, with the times set by hand, so nothing here depends on the clock.
 */
import type { Locator, Page } from '@playwright/test'
import { z } from 'zod'

import { shiftDate } from '../../../src/lib/dates'
import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'
import { getLatestWeekdayDate } from '../timesheet/support'

const PROJECT_WEEKS_BACK: Record<string, number> = { android: 4, iphone: 5 }
const DAY_PATH = '/api/job/workshop/timesheets/'

/** What today's screen costs for the same day, measured before this work. */
const TAPS_BEFORE = 31
const KEYSTROKES_BEFORE = 15

function pastWeekday(projectName: string): string {
  const weeksBack = PROJECT_WEEKS_BACK[projectName]
  if (weeksBack === undefined) throw new Error(`No fill day for project "${projectName}"`)
  return shiftDate(getLatestWeekdayDate(), -7 * weeksBack)
}

const jobsSchema = z.object({
  jobs: z.array(z.object({ id: z.string(), job_number: z.number() })),
  pinned_job_ids: z.array(z.string()),
  recent_job_ids: z.array(z.string()),
})

const daySchema = z.object({
  entries: z.array(
    z.object({ job_number: z.number(), start_time: z.string(), end_time: z.string() }),
  ),
})

async function setBreakTimes(page: Page, start: string, finish: string): Promise<void> {
  await autoId(page, 'BreakSheet-start').fill(start)
  await autoId(page, 'BreakSheet-finish').fill(finish)
  await autoId(page, 'BreakSheet-times-save').tap()
}

test.use({ loginRole: 'workshop' })

test('a three-job day is filled from buttons and sent, around the breaks', async ({
  authenticatedPage: page,
}, testInfo) => {
  const day = pastWeekday(testInfo.project.name)
  const fill = autoId(page, 'DayCard-fill')
  const breakBlock = (words: string) =>
    page.locator('[data-automation-id="WorkshopTimesheetCalendar"] [data-break-id]', {
      hasText: words,
    })

  // The buttons the sheet will offer, in its order: the shop's standing jobs,
  // then the jobs the workshop has just been on.
  const listed = jobsSchema.parse(await (await page.request.get('/api/timesheets/jobs/')).json())
  const numberOf = new Map(listed.jobs.map((job) => [job.id, job.job_number]))
  const buttons = [...listed.pinned_job_ids, ...listed.recent_job_ids].map((id) =>
    z.number().parse(numberOf.get(id)),
  )
  const [first, second, third] = buttons
  if (first === undefined || second === undefined || third === undefined) {
    throw new Error(`The fill sheet offers ${buttons.length} job buttons; this day needs three.`)
  }

  await test.step('setting the day puts the standard breaks on it', async () => {
    await expect(autoId(page, 'DayCard')).toBeVisible()
    await page.goto(`/timesheets/my-time?date=${day}`)
    // Nobody has clocked this day: the card offers the company's standard hours.
    await expect(fill).toHaveText(/^Standard hours \d{2}:\d{2} to \d{2}:\d{2}$/)
    await autoId(page, 'DayCard-change-times').tap()
    await autoId(page, 'DayCard-start').fill('06:30')
    await autoId(page, 'DayCard-finish').fill('15:00')
    await autoId(page, 'DayCard-times-save').tap()

    await expect(breakBlock('Paid break 08:30 to 08:45')).toBeVisible()
    await expect(breakBlock('Lunch 11:30 to 12:00')).toBeVisible()
    await expect(breakBlock('Paid break 13:30 to 13:45')).toBeVisible()
    // Here for 8h 30m less lunch; his two paid breaks are entered for him.
    await expect(fill).toHaveText('8h to fill, 30m breaks, 0h entered, 7h 30m to go')
    await testInfo.attach('day-with-breaks', {
      body: await page.screenshot({ animations: 'disabled', fullPage: true }),
      contentType: 'image/png',
    })
  })

  await test.step('breaks are his: moved, removed and added back', async () => {
    await breakBlock('Lunch').tap()
    await setBreakTimes(page, '12:00', '12:30')
    await expect(breakBlock('Lunch 12:00 to 12:30')).toBeVisible()
    await expect(fill).toHaveText('8h to fill, 30m breaks, 0h entered, 7h 30m to go')

    // He worked through lunch: it goes, and the half hour is his to fill.
    await breakBlock('Lunch').tap()
    await autoId(page, 'BreakSheet-remove').tap()
    await expect(breakBlock('Lunch')).toHaveCount(0)
    await expect(fill).toHaveText('8h 30m to fill, 30m breaks, 0h entered, 8h to go')

    // A paid break he did not take is paid time he books to a job instead.
    await breakBlock('Paid break 13:30').tap()
    await autoId(page, 'BreakSheet-remove').tap()
    await expect(breakBlock('Paid break 13:30')).toHaveCount(0)
    await expect(fill).toHaveText('8h 30m to fill, 15m breaks, 0h entered, 8h 15m to go')

    await autoId(page, 'DayCard-add-break').tap()
    await autoId(page, 'BreakSheet-paid').tap()
    await setBreakTimes(page, '13:30', '13:45')
    await expect(breakBlock('Paid break 13:30 to 13:45')).toBeVisible()
    await autoId(page, 'DayCard-add-break').tap()
    await autoId(page, 'BreakSheet-unpaid').tap()
    await setBreakTimes(page, '11:30', '12:00')
    await expect(breakBlock('Unpaid break 11:30 to 12:00')).toBeVisible()
    await expect(fill).toHaveText('8h to fill, 30m breaks, 0h entered, 7h 30m to go')
  })

  // Every tap from here to the day being sent is counted: this is the whole
  // cost of recording the day. On a live day the first of them is Clock out,
  // which opens the sheet; on this past day "Fill and send" stands in for it.
  let taps = 0
  const tap = async (target: Locator) => {
    await target.tap()
    taps += 1
  }
  const sum = autoId(page, 'FillDaySheet-sum')

  await test.step('three jobs, no times, no adding up', async () => {
    await tap(autoId(page, 'DayCard-fill-and-send'))
    await expect(sum).toHaveText('8h to fill, 30m breaks, 0h entered, 7h 30m to go')

    await tap(autoId(page, `FillDaySheet-job-${first}`))
    await tap(autoId(page, 'FillDaySheet-row-0-hours-3'))
    await expect(sum).toHaveText('8h to fill, 30m breaks, 3h entered, 4h 30m to go')

    await tap(autoId(page, `FillDaySheet-job-${second}`))
    await tap(autoId(page, 'FillDaySheet-row-1-hours-2'))
    await expect(sum).toHaveText('8h to fill, 30m breaks, 5h entered, 2h 30m to go')

    await tap(autoId(page, `FillDaySheet-job-${third}`))
    await expect(autoId(page, 'FillDaySheet-row-2-rest')).toHaveText('The rest (2h 30m)')
    await tap(autoId(page, 'FillDaySheet-row-2-rest'))
    await expect(sum).toHaveText('8h to fill, 30m breaks, 7h 30m entered. All filled')
    // The buttons fill the same field he can type in.
    await expect(autoId(page, 'FillDaySheet-row-2-hours')).toHaveValue('2.5')
    await testInfo.attach('fill-sheet', {
      body: await page.screenshot({ animations: 'disabled' }),
      contentType: 'image/png',
    })

    await tap(autoId(page, 'FillDaySheet-send'))
    await expect(page.getByText('Day sent to the office.')).toBeVisible()
  })

  await test.step('the day reads sent, each job one entry stepping over the breaks', async () => {
    await expect(autoId(page, 'DayCard-state')).toContainText('Sent, waiting for approval')
    await expect(fill).toHaveText('8h to fill, 30m breaks, 7h 30m entered. All filled')
    const saved = daySchema.parse(await (await page.request.get(`${DAY_PATH}?date=${day}`)).json())
    expect(
      saved.entries.map((entry) => [entry.job_number, entry.start_time, entry.end_time]),
    ).toEqual([
      // 3h over the morning break, 2h over lunch, 2h 30m over the afternoon break.
      [first, '06:30:00', '09:45:00'],
      [second, '09:45:00', '12:15:00'],
      [third, '12:15:00', '15:00:00'],
    ])
    await testInfo.attach('day-sent', {
      body: await page.screenshot({ animations: 'disabled', fullPage: true }),
      contentType: 'image/png',
    })
  })

  testInfo.annotations.push({
    type: 'taps for a three-job day',
    description: `${taps} taps and 0 keystrokes; the screen before needed about ${TAPS_BEFORE} taps and ${KEYSTROKES_BEFORE} keystrokes`,
  })
  console.log(`[fill-day] ${testInfo.project.name}: ${taps} taps, 0 keystrokes for a three-job day`)
  expect(taps).toBe(8)
})
