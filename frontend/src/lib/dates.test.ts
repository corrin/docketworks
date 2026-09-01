import { describe, expect, it } from 'vitest'

import { isIsoMonthString, nextWeekday, shiftDate, shiftMonth, weekdayAdjusted } from './dates'

// 2026-08-07 is a Friday; 08/08 Sat, 09/08 Sun, 10/08 Mon.

describe('shiftDate', () => {
  it('shifts across month boundaries in local time', () => {
    expect(shiftDate('2026-08-31', 1)).toBe('2026-09-01')
    expect(shiftDate('2026-09-01', -1)).toBe('2026-08-31')
  })
})

describe('nextWeekday', () => {
  it('steps one day when weekends are enabled', () => {
    expect(nextWeekday('2026-08-07', 1, true)).toBe('2026-08-08')
    expect(nextWeekday('2026-08-10', -1, true)).toBe('2026-08-09')
  })

  it('skips the weekend forwards when disabled', () => {
    expect(nextWeekday('2026-08-07', 1, false)).toBe('2026-08-10')
  })

  it('skips the weekend backwards when disabled', () => {
    expect(nextWeekday('2026-08-10', -1, false)).toBe('2026-08-07')
  })
})

describe('weekdayAdjusted', () => {
  it('pushes Saturday and Sunday to Monday when weekends are disabled', () => {
    expect(weekdayAdjusted('2026-08-08', false)).toBe('2026-08-10')
    expect(weekdayAdjusted('2026-08-09', false)).toBe('2026-08-10')
  })

  it('leaves weekdays and enabled weekends alone', () => {
    expect(weekdayAdjusted('2026-08-07', false)).toBe('2026-08-07')
    expect(weekdayAdjusted('2026-08-08', true)).toBe('2026-08-08')
  })
})

describe('isIsoMonthString', () => {
  it('accepts a real month in the range the reports API serves', () => {
    expect(isIsoMonthString('2026-09')).toBe(true)
    expect(isIsoMonthString('2000-01')).toBe(true)
  })

  it('rejects years the server would 422', () => {
    // The bound mirrors apps/accounting/api.py so a hand-edited URL falls
    // back to the current month instead of rendering a server error.
    expect(isIsoMonthString('1999-06')).toBe(false)
    expect(isIsoMonthString('2101-06')).toBe(false)
  })

  it('rejects malformed and over-specified values', () => {
    expect(isIsoMonthString('2026-13')).toBe(false)
    expect(isIsoMonthString('2026-00')).toBe(false)
    expect(isIsoMonthString('2026-9')).toBe(false)
    expect(isIsoMonthString('2026-09-01')).toBe(false)
    expect(isIsoMonthString('')).toBe(false)
  })
})

describe('shiftMonth', () => {
  it('rolls the year over in both directions', () => {
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
  })

  it('refuses a full date rather than silently dropping the day', () => {
    // shiftDate has the same signature and DOES take YYYY-MM-DD, so passing
    // one here is the likely mistake; before the guard it returned '2026-10'.
    expect(() => shiftMonth('2026-09-15', 1)).toThrow(/Not a YYYY-MM month/)
    expect(() => shiftMonth('1999-06', 1)).toThrow(/Not a YYYY-MM month/)
  })

  it('shifts within a year and pads the month', () => {
    expect(shiftMonth('2026-09', -1)).toBe('2026-08')
    expect(shiftMonth('2026-09', 1)).toBe('2026-10')
    expect(shiftMonth('2026-11', -2)).toBe('2026-09')
  })
})
