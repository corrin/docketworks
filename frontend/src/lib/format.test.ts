import { describe, expect, it } from 'vitest'

import {
  formatClock,
  formatCurrency,
  formatDateTime,
  formatEventType,
  formatPercentage,
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
