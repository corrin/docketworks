import { describe, expect, it } from 'vitest'
import { clampSyncProgress } from '@/composables/useXeroAuth'

describe('clampSyncProgress', () => {
  it('keeps sync progress in the fraction range expected by XeroView', () => {
    expect(clampSyncProgress(0.42)).toBe(0.42)
    expect(clampSyncProgress(1.1)).toBe(1)
    expect(clampSyncProgress(120)).toBe(1)
  })

  it('coerces invalid progress values to zero', () => {
    expect(clampSyncProgress(-0.1)).toBe(0)
    expect(clampSyncProgress(Number.NaN)).toBe(0)
    expect(clampSyncProgress(Number.POSITIVE_INFINITY)).toBe(0)
  })
})
