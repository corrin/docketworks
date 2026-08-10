import { describe, expect, it } from 'vitest'

import { nextWeekday, shiftDate, weekdayAdjusted } from './dates'

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
