import { describe, expect, it } from 'vitest'
import { formatDate, formatDateTime, formatDayDate } from '../string-formatting'

// Local-time ISO string (no Z suffix) so the formatted date parts are stable
// regardless of the timezone the tests run in.
const WED_10_JUN_2026 = '2026-06-10T14:30:00'

describe('formatDate', () => {
  it('formats a date-only display value', () => {
    expect(formatDate(WED_10_JUN_2026)).toBe('10 Jun 2026')
  })

  it('returns "-" for absent values', () => {
    expect(formatDate(null)).toBe('-')
    expect(formatDate(undefined)).toBe('-')
    expect(formatDate('')).toBe('-')
  })

  it('throws on an unparseable date string', () => {
    expect(() => formatDate('not-a-date')).toThrow('Invalid date: not-a-date')
  })
})

describe('formatDateTime', () => {
  it('formats a date+time display value', () => {
    const result = formatDateTime(WED_10_JUN_2026)
    expect(result).toContain('10 Jun 2026')
    expect(result).toContain('2:30')
  })

  it('returns "-" for absent values', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime(undefined)).toBe('-')
    expect(formatDateTime('')).toBe('-')
  })

  it('throws on an unparseable date string', () => {
    expect(() => formatDateTime('garbage')).toThrow('Invalid date: garbage')
  })
})

describe('formatDayDate', () => {
  it('formats a weekday+date display value', () => {
    // en-NZ ICU renders the short weekday with a trailing comma.
    expect(formatDayDate(WED_10_JUN_2026)).toBe('Wed, 10 Jun')
  })

  it('returns "-" for absent values', () => {
    expect(formatDayDate(null)).toBe('-')
    expect(formatDayDate(undefined)).toBe('-')
    expect(formatDayDate('')).toBe('-')
  })

  it('throws on an unparseable date string', () => {
    expect(() => formatDayDate('2026-13-99nonsense')).toThrow('Invalid date: 2026-13-99nonsense')
  })
})
