import { describe, expect, it } from 'vitest'

import { formatHoursDisplay } from '@/lib/format'
import { parseHoursInput } from './hours'

describe('parseHoursInput', () => {
  it('parses decimals', () => {
    expect(parseHoursInput('1.5')).toBe(1.5)
    expect(parseHoursInput('8')).toBe(8)
  })

  it('parses fractional forms', () => {
    expect(parseHoursInput('1 1/4')).toBe(1.25)
    expect(parseHoursInput('3/4')).toBe(0.75)
  })

  // Opus: formatHoursDisplay lives in lib/format.ts and its own cases are
  // tested there. What must be asserted HERE is that the two still meet — a
  // display change the parser cannot read back breaks the hours input, and
  // neither file's own tests would notice.
  it('round-trips the humanised display form', () => {
    expect(parseHoursInput(formatHoursDisplay(3.5))).toBe(3.5)
    expect(parseHoursInput(formatHoursDisplay(0.75))).toBe(0.75)
    expect(parseHoursInput('3h 30m')).toBe(3.5)
    expect(parseHoursInput('2h')).toBe(2)
    expect(parseHoursInput('45m')).toBe(0.75)
    expect(parseHoursInput('3h 45m')).toBe(3.75)
  })

  it('clamps to 24 and rounds to 2dp', () => {
    expect(parseHoursInput('25')).toBe(24)
    expect(parseHoursInput('1.333333')).toBe(1.33)
  })

  it('is null on blank, garbage, negatives and zero denominators', () => {
    expect(parseHoursInput('')).toBeNull()
    expect(parseHoursInput('   ')).toBeNull()
    expect(parseHoursInput('garbage')).toBeNull()
    expect(parseHoursInput('-1')).toBeNull()
    expect(parseHoursInput('1/0')).toBeNull()
    expect(parseHoursInput('1 1/0')).toBeNull()
  })
})
