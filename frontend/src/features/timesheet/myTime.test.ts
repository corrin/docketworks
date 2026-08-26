import { describe, expect, it } from 'vitest'

import type { WorkshopTimesheetEntryOut } from '@/api'

import { calendarEvent, deriveHoursFromTimes, eventTitle, splitDayEntries } from './myTime'

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
