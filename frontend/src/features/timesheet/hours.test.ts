import { describe, expect, it } from 'vitest'

import { formatHoursDisplay, parseHoursInput } from './hours'

describe('parseHoursInput', () => {
  it('parses decimals', () => {
    expect(parseHoursInput('1.5', 0)).toBe(1.5)
    expect(parseHoursInput('8', 0)).toBe(8)
  })

  it('parses fractional forms', () => {
    expect(parseHoursInput('1 1/4', 0)).toBe(1.25)
    expect(parseHoursInput('3/4', 0)).toBe(0.75)
  })

  it('round-trips the humanised display form', () => {
    expect(parseHoursInput('3h 30m', 0)).toBe(3.5)
    expect(parseHoursInput('2h', 0)).toBe(2)
    expect(parseHoursInput('45m', 0)).toBe(0.75)
    expect(parseHoursInput('3h 45m', 0)).toBe(3.75)
  })

  it('clamps to 24 and rounds to 2dp', () => {
    expect(parseHoursInput('25', 0)).toBe(24)
    expect(parseHoursInput('1.333333', 0)).toBe(1.33)
  })

  it('falls back on blank, garbage, negatives and zero denominators', () => {
    expect(parseHoursInput('', 2)).toBe(2)
    expect(parseHoursInput('   ', 2)).toBe(2)
    expect(parseHoursInput('garbage', 2)).toBe(2)
    expect(parseHoursInput('-1', 2)).toBe(2)
    expect(parseHoursInput('1/0', 2)).toBe(2)
    expect(parseHoursInput('1 1/0', 2)).toBe(2)
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
