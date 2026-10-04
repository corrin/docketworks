import { describe, expect, it } from 'vitest'

import type { WorkshopTimesheetEntryOut } from '@/api'

import {
  adjustEnd,
  billingChangeFields,
  billsItsTime,
  calendarEvent,
  defaultNewEntryRange,
  deriveHoursFromTimes,
  distinctJobCount,
  entryUpdateBody,
  eventTitle,
  fillGapToNextEntry,
  jobChangeFields,
  lastUsedJobId,
  rateLabel,
  shownBillable,
  slotFrom,
  slotFromNow,
  splitDayEntries,
  workingDayStart,
} from './myTime'

function makeEntry(overrides: Partial<WorkshopTimesheetEntryOut> = {}): WorkshopTimesheetEntryOut {
  return {
    id: 'e1',
    job_id: 'j1',
    job_number: 42,
    job_name: 'Handrail',
    company_name: 'ABC',
    description: 'Welding',
    hours: 2.5,
    accounting_date: '2026-08-26',
    start_time: '08:00:00',
    end_time: '10:30:00',
    is_billable: true,
    wage_rate_multiplier: 1,
    bill_rate_multiplier: 1,
    created_at: '2026-08-26T08:00:00Z',
    updated_at: '2026-08-26T08:00:00Z',
    ...overrides,
  }
}

describe('deriveHoursFromTimes', () => {
  it('derives decimal hours from an HH:mm pair', () => {
    expect(deriveHoursFromTimes('08:00', '09:30')).toBe(1.5)
  })

  it('rounds to two decimals so 20 minutes books as 0.33', () => {
    expect(deriveHoursFromTimes('08:00', '08:20')).toBe(0.33)
  })

  it('returns null when either time is blank', () => {
    expect(deriveHoursFromTimes('', '09:00')).toBeNull()
    expect(deriveHoursFromTimes('08:00', '')).toBeNull()
  })

  it('returns null when the end is at or before the start', () => {
    expect(deriveHoursFromTimes('09:00', '08:00')).toBeNull()
    expect(deriveHoursFromTimes('09:00', '09:00')).toBeNull()
  })
})

describe('splitDayEntries', () => {
  it('separates entries with a full time pair from the rest', () => {
    const timed = makeEntry({ id: 'a' })
    const noStart = makeEntry({ id: 'b', start_time: null })
    const noEnd = makeEntry({ id: 'c', end_time: null })

    const split = splitDayEntries([timed, noStart, noEnd])

    expect(split.timed.map((entry) => entry.id)).toEqual(['a'])
    expect(split.untimed.map((entry) => entry.id)).toEqual(['b', 'c'])
  })
})

describe('eventTitle', () => {
  it('carries the job number, name, and humanised duration', () => {
    expect(eventTitle(makeEntry())).toBe('#42 Handrail (2h 30m)')
  })
})

describe('jobChangeFields', () => {
  it('is empty when the job did not change', () => {
    expect(jobChangeFields(makeEntry(), 'j1')).toEqual({})
  })

  it("a move sends the job alone; billability is the server's rule", () => {
    expect(jobChangeFields(makeEntry({ is_billable: false }), 'j2')).toEqual({ job_id: 'j2' })
  })
})

describe('billingChangeFields', () => {
  it('sends nothing when the tick is untouched and the rate is as stored', () => {
    const entry = makeEntry({ is_billable: false, wage_rate_multiplier: 1.5 })

    expect(billingChangeFields(entry, { billableChoice: null, rateMultiplier: 1.5 })).toEqual({})
  })

  it('sends the tick the user set, even when it matches the stored value', () => {
    // An explicit unbillable choice has to reach the server, or a move off a
    // shop job re-bills the entry against what the user asked for.
    const entry = makeEntry({ is_billable: false })

    expect(billingChangeFields(entry, { billableChoice: false, rateMultiplier: 1 })).toEqual({
      is_billable: false,
    })
  })

  it('sends the rate only when the user changed it', () => {
    expect(billingChangeFields(makeEntry(), { billableChoice: null, rateMultiplier: 2 })).toEqual({
      wage_rate_multiplier: 2,
    })
  })
})

describe('shownBillable', () => {
  const normal = { id: 'j1', shop_job: false, status: 'in_progress' }
  const otherNormal = { id: 'j2', shop_job: false, status: 'in_progress' }
  const shop = { id: 'shop', shop_job: true, status: 'special' }
  const special = { id: 'leave', shop_job: false, status: 'special' }

  it('shop and special jobs cannot bill their time', () => {
    expect(billsItsTime(normal)).toBe(true)
    expect(billsItsTime(shop)).toBe(false)
    expect(billsItsTime(special)).toBe(false)
  })

  it('a new entry is billable until the user says otherwise', () => {
    const untouched = { entry: null, sourceJob: null, selectedJob: normal, billableChoice: null }

    expect(shownBillable(untouched)).toBe(true)
    expect(shownBillable({ ...untouched, billableChoice: false })).toBe(false)
  })

  it('a job that cannot bill shows unticked whatever was chosen', () => {
    expect(
      shownBillable({ entry: null, sourceJob: null, selectedJob: shop, billableChoice: true }),
    ).toBe(false)
  })

  it('an untouched edit shows the stored value, also across a normal-to-normal move', () => {
    const entry = makeEntry({ job_id: 'j1', is_billable: false })

    expect(
      shownBillable({ entry, sourceJob: normal, selectedJob: normal, billableChoice: null }),
    ).toBe(false)
    expect(
      shownBillable({ entry, sourceJob: normal, selectedJob: otherNormal, billableChoice: null }),
    ).toBe(false)
  })

  it('an untouched move off a shop job shows billable, as the server will save it', () => {
    const entry = makeEntry({ job_id: 'shop', is_billable: false })

    expect(
      shownBillable({ entry, sourceJob: shop, selectedJob: normal, billableChoice: null }),
    ).toBe(true)
    expect(
      shownBillable({ entry, sourceJob: shop, selectedJob: normal, billableChoice: false }),
    ).toBe(false)
  })
})

describe('workingDayStart', () => {
  const starts = {
    mon_start: '07:00:00',
    tue_start: '07:15:00',
    wed_start: '07:30:00',
    thu_start: '07:45:00',
    fri_start: '06:30:00',
  }

  it("is the configured start for the date's weekday", () => {
    expect(workingDayStart('2026-10-05', starts)).toBe('07:00') // Monday
    expect(workingDayStart('2026-10-09', starts)).toBe('06:30') // Friday
  })

  it('is 08:00 on a weekend, which has no configured hours', () => {
    expect(workingDayStart('2026-10-03', starts)).toBe('08:00') // Saturday
    expect(workingDayStart('2026-10-04', starts)).toBe('08:00') // Sunday
  })
})

describe('distinctJobCount', () => {
  it('counts each job once however many entries it has', () => {
    const entries = [
      makeEntry({ id: 'a', job_id: 'j1' }),
      makeEntry({ id: 'b', job_id: 'j1' }),
      makeEntry({ id: 'c', job_id: 'j2' }),
    ]

    expect(distinctJobCount(entries)).toBe(2)
  })
})

describe('rateLabel', () => {
  it('names ordinary time and shows the multiplier otherwise', () => {
    expect(rateLabel(1)).toBe('Ord')
    expect(rateLabel(1.5)).toBe('1.5x')
    expect(rateLabel(2)).toBe('2x')
  })
})

describe('slotFrom', () => {
  it('opens a half-hour slot', () => {
    expect(slotFrom('08:00')).toEqual({ start: '08:00', end: '08:30' })
  })

  it('stops at the last minute of the day', () => {
    expect(slotFrom('23:45')).toEqual({ start: '23:45', end: '23:59' })
  })
})

describe('defaultNewEntryRange', () => {
  const morning = makeEntry({ id: 'a', start_time: '08:00:00', end_time: '10:30:00' })
  const midday = makeEntry({ id: 'b', start_time: '11:00:00', end_time: '12:15:00' })

  it('starts at the tapped slot when there is one', () => {
    expect(defaultNewEntryRange([morning, midday], '07:30', '14:00')).toEqual({
      start: '14:00',
      end: '14:30',
    })
  })

  it("starts where the day's latest entry finished, whatever the list order", () => {
    expect(defaultNewEntryRange([midday, morning], '07:30', null)).toEqual({
      start: '12:15',
      end: '12:45',
    })
  })

  it('starts at the working-day start on an empty day', () => {
    expect(defaultNewEntryRange([], '07:30', null)).toEqual({ start: '07:30', end: '08:00' })
  })

  it('ignores untimed entries, which have no finish', () => {
    const untimed = makeEntry({ start_time: null, end_time: null })

    expect(defaultNewEntryRange([untimed], '07:30', null)).toEqual({ start: '07:30', end: '08:00' })
  })
})

describe('lastUsedJobId', () => {
  it('is the job of the entry booked most recently', () => {
    const earlier = makeEntry({ id: 'a', job_id: 'j1', created_at: '2026-08-26T08:00:00Z' })
    const later = makeEntry({ id: 'b', job_id: 'j2', created_at: '2026-08-26T11:00:00Z' })

    expect(lastUsedJobId([later, earlier])).toBe('j2')
  })

  it('is null on an empty day', () => {
    expect(lastUsedJobId([])).toBeNull()
  })
})

describe('slotFromNow', () => {
  it('opens a slot at the wall-clock minute', () => {
    expect(slotFromNow(new Date(2026, 7, 26, 13, 7, 45))).toEqual({ start: '13:07', end: '13:37' })
  })
})

describe('adjustEnd', () => {
  const range = { start: '08:00', end: '08:30' }

  it('moves the end and keeps the start', () => {
    expect(adjustEnd(range, 15)).toEqual({ start: '08:00', end: '08:45' })
    expect(adjustEnd(range, -5)).toEqual({ start: '08:00', end: '08:25' })
  })

  it('leaves a one-minute entry when pulled back to the start or past it', () => {
    expect(adjustEnd({ start: '08:00', end: '08:05' }, -5)).toEqual({
      start: '08:00',
      end: '08:01',
    })
    expect(adjustEnd({ start: '08:00', end: '08:03' }, -5)).toEqual({
      start: '08:00',
      end: '08:01',
    })
  })

  it('stops at the last minute of the day', () => {
    expect(adjustEnd({ start: '23:00', end: '23:45' }, 30)).toEqual({
      start: '23:00',
      end: '23:59',
    })
  })
})

describe('fillGapToNextEntry', () => {
  const afternoon = makeEntry({ id: 'a', start_time: '13:00:00', end_time: '15:00:00' })
  const morning = makeEntry({ id: 'b', start_time: '08:00:00', end_time: '09:00:00' })
  const lateAfternoon = makeEntry({ id: 'c', start_time: '15:30:00', end_time: '16:00:00' })

  it("runs up to the day's next start", () => {
    expect(fillGapToNextEntry('09:00', [lateAfternoon, afternoon, morning])).toEqual({
      start: '09:00',
      end: '13:00',
    })
  })

  it('runs to the end of the day when nothing follows', () => {
    expect(fillGapToNextEntry('16:00', [afternoon, morning])).toEqual({
      start: '16:00',
      end: '23:59',
    })
  })
})

describe('entryUpdateBody', () => {
  const form = {
    jobId: 'j1',
    start: '08:00',
    end: '09:30',
    hours: 1.5,
    description: 'Welding',
  }

  it('carries the pair, derived hours, and description', () => {
    expect(entryUpdateBody(makeEntry(), form)).toEqual({
      entry_id: 'e1',
      hours: 1.5,
      start_time: '08:00:00',
      end_time: '09:30:00',
      description: 'Welding',
    })
  })

  it('leaves times and hours alone on an untimed entry edited without them', () => {
    const untimed = makeEntry({ start_time: null, end_time: null })

    expect(entryUpdateBody(untimed, { ...form, start: '', end: '', hours: null })).toEqual({
      entry_id: 'e1',
      description: 'Welding',
    })
  })

  it('folds in the job when it moved', () => {
    const body = entryUpdateBody(makeEntry(), { ...form, jobId: 'j2' })

    expect(body.job_id).toBe('j2')
    expect(body).not.toHaveProperty('is_billable')
  })

  it('sends null to clear a blank description', () => {
    expect(entryUpdateBody(makeEntry(), { ...form, description: '  ' }).description).toBeNull()
  })
})

describe('calendarEvent', () => {
  it('anchors the entry times onto the given day', () => {
    const [timedEntry] = splitDayEntries([makeEntry()]).timed
    if (!timedEntry) throw new Error('expected a timed entry')
    const event = calendarEvent(timedEntry)

    expect(event).toEqual({
      id: 'e1',
      title: '#42 Handrail (2h 30m)',
      start: '2026-08-26T08:00:00',
      end: '2026-08-26T10:30:00',
    })
  })
})
