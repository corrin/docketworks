import { describe, expect, it } from 'vitest'

import {
  formatClock,
  formatCurrency,
  formatDateTime,
  formatDate,
  formatEventType,
  formatHoursDisplay,
  formatMonth,
  formatPercentage,
  formatWholeCurrency,
  localIsoDate,
  localIsoMonth,
} from './format'

describe('formatCurrency', () => {
  it('renders dollars with cents and grouping', () => {
    expect(formatCurrency(1234.5)).toBe('$1,234.50')
    expect(formatCurrency(0)).toBe('$0.00')
  })

  it('renders negatives with a leading sign', () => {
    expect(formatCurrency(-987.65)).toBe('-$987.65')
  })
})

describe('formatPercentage', () => {
  it('renders percentage points with one decimal', () => {
    expect(formatPercentage(12.5)).toBe('12.5%')
    expect(formatPercentage(0)).toBe('0.0%')
    expect(formatPercentage(100)).toBe('100.0%')
  })
})

describe('formatDateTime', () => {
  it('renders the date and the time of day, short', () => {
    // The instant is built from LOCAL parts, so the expected string holds in
    // whatever zone the runner sits in — the assertion is about the format,
    // not about the machine.
    expect(formatDateTime(new Date(2026, 7, 9, 14, 30).toISOString())).toBe('09/08/2026, 2:30 pm')
  })

  it('renders one instant identically however its offset is spelled', () => {
    expect(formatDateTime('2026-08-09T02:30:00Z')).toBe(formatDateTime('2026-08-09T14:30:00+12:00'))
  })
})

describe('formatEventType', () => {
  it('title-cases each underscore-separated word', () => {
    expect(formatEventType('costline_updated')).toBe('Costline Updated')
    expect(formatEventType('manual_note')).toBe('Manual Note')
    expect(formatEventType('created')).toBe('Created')
  })
})

describe('formatClock', () => {
  it('reads m:ss with minutes unbounded', () => {
    expect(formatClock(0)).toBe('0:00')
    expect(formatClock(7)).toBe('0:07')
    expect(formatClock(615.744)).toBe('10:15')
    expect(formatClock(4320)).toBe('72:00')
  })
})

describe('formatWholeCurrency', () => {
  it('drops the cents a precision-toggled report does not want', () => {
    expect(formatWholeCurrency(1234)).toBe('$1,234')
    expect(formatWholeCurrency(-1234.56)).toBe('-$1,235')
  })

  it('stays distinguishable from formatCurrency on the same value', () => {
    // The two must never be interchangeable by accident: a report picks one
    // and uses it everywhere, which is only enforceable if they differ.
    expect(formatWholeCurrency(1234)).not.toBe(formatCurrency(1234))
  })
})

describe('formatMonth', () => {
  it('renders a YYYY-MM month short-form, matching formatDate', () => {
    // en-NZ abbreviates September as 'Sept', which is exactly what
    // formatDate emits ('02 Sept 2026') — the point is that they agree.
    expect(formatMonth('2026-09')).toBe('Sept 2026')
    expect(formatMonth('2026-01')).toBe('Jan 2026')
    expect(formatMonth('2026-09')).toBe(formatDate('2026-09-02').slice(3))
  })

  it('does not slip to the previous month behind UTC', () => {
    // Parsing '2026-09-01' yields UTC midnight; formatting it in a local
    // timezone behind UTC would render August.
    expect(formatMonth('2026-09')).toBe('Sept 2026')
    expect(formatMonth('2026-12')).toBe('Dec 2026')
  })
})

describe('localIsoMonth', () => {
  it('is localIsoDate truncated, so both share one timezone rule', () => {
    expect(localIsoMonth()).toBe(localIsoDate().slice(0, 7))
    expect(localIsoMonth()).toMatch(/^\d{4}-\d{2}$/)
  })
})

describe('formatHoursDisplay', () => {
  it('formats whole hours as Nh', () => {
    expect(formatHoursDisplay(2)).toBe('2h')
    expect(formatHoursDisplay(8)).toBe('8h')
  })

  it('formats mixed hours as Nh Mm', () => {
    expect(formatHoursDisplay(3.5)).toBe('3h 30m')
    expect(formatHoursDisplay(1.25)).toBe('1h 15m')
  })

  it('formats sub-hour values as Mm', () => {
    expect(formatHoursDisplay(0.25)).toBe('15m')
  })

  it('formats zero and non-finite as 0h', () => {
    expect(formatHoursDisplay(0)).toBe('0h')
    expect(formatHoursDisplay(Number.NaN)).toBe('0h')
    expect(formatHoursDisplay(null)).toBe('0h')
    expect(formatHoursDisplay(undefined)).toBe('0h')
  })
})
