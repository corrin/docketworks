import { describe, expect, it } from 'vitest'

import { formatCurrency, formatPercentage } from './format'

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
