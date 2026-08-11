import { describe, expect, it } from 'vitest'

import { parseDecimalInput, trimDecimal } from './decimal'

describe('parseDecimalInput', () => {
  it('accepts plain and comma-grouped numbers, canonicalised like the display', () => {
    // Trimmed like trimDecimal, so the send-dedupe compares like with like:
    // re-entering '25.00' over a displayed '25' must be a no-op, not a PATCH
    // that re-derives (and wipes) an overridden unit revenue.
    expect(parseDecimalInput('1,250.50')).toBe('1250.5')
    expect(parseDecimalInput('25.00')).toBe('25')
    expect(parseDecimalInput(' 3 ')).toBe('3')
  })

  it('returns null for garbage and non-finite input', () => {
    expect(parseDecimalInput('abc')).toBeNull()
    expect(parseDecimalInput('')).toBeNull()
    expect(parseDecimalInput('Infinity')).toBeNull()
  })

  it('rejects numeric-but-non-decimal syntax Number() would accept', () => {
    // Number() parses hex/octal/binary literals and bare exponents as
    // finite numbers; none is valid Decimal wire syntax.
    expect(parseDecimalInput('0x10')).toBeNull()
    expect(parseDecimalInput('0b101')).toBeNull()
    expect(parseDecimalInput('0o17')).toBeNull()
    expect(parseDecimalInput('1e10')).toBeNull()
  })
})

describe('trimDecimal', () => {
  it('strips trailing zeros for input display', () => {
    expect(trimDecimal('3.000')).toBe('3')
    expect(trimDecimal('25.00')).toBe('25')
    expect(trimDecimal('1000.50')).toBe('1000.5')
    expect(trimDecimal('0.2500')).toBe('0.25')
  })

  it('leaves non-fixed-point strings alone — trimming an exponent form would corrupt it', () => {
    expect(trimDecimal('')).toBe('')
    expect(trimDecimal('12')).toBe('12')
    expect(trimDecimal('1.5e10')).toBe('1.5e10')
  })
})
