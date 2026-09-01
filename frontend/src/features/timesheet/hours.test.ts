import { describe, expect, it } from 'vitest'

import { formatHoursDisplay } from '@/lib/format'
import { parseHoursInput } from './hours'

describe('parseHoursInput', () => {
  it('parses decimals', () => {
    expect(parseHoursInput('1.5', 0)).toBe(1.5)
    expect(parseHoursInput('8', 0)).toBe(8)
  })

  it('parses fractional forms', () => {
    expect(parseHoursInput('1 1/4', 0)).toBe(1.25)
    expect(parseHoursInput('3/4', 0)).toBe(0.75)
  })

  // formatHoursDisplay lives in lib/format.ts; its own cases are tested
  // there. What must be asserted HERE is that the two still meet — a change
  // to the display form that the parser cannot read back breaks the hours
  // input, and neither file's own tests would notice.
  it('round-trips the humanised display form', () => {
    expect(parseHoursInput(formatHoursDisplay(3.5), 0)).toBe(3.5)
    expect(parseHoursInput(formatHoursDisplay(0.75), 0)).toBe(0.75)
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
