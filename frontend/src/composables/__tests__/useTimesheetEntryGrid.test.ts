import { describe, expect, it, beforeEach } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

import { useTimesheetEntryGrid } from '../useTimesheetEntryGrid'

describe('useTimesheetEntryGrid', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('applies the rate multiplier when calculating wage', () => {
    const companyDefaults = ref(null)
    const jobs = ref<Record<string, unknown>[]>([])
    const noop = async () => {
      /* no-op */
    }

    const { createEntryFromRow } = useTimesheetEntryGrid(companyDefaults, jobs, noop, noop)

    const entry = createEntryFromRow({
      jobNumber: '95196',
      job_number: 95196,
      hours: 2,
      wageRate: 30,
      rate: '1.5',
      billable: true,
      description: 'Fabrication',
      staffId: 'staff-1',
      date: '2024-05-01',
    } as unknown as Parameters<typeof createEntryFromRow>[0])

    expect(entry.rateMultiplier).toBe(1.5)
    expect(entry.meta?.wage_rate_multiplier).toBe(1.5)
    expect(entry.wage).toBe(90) // 2 hours * 30 wageRate * 1.5x
  })

  it('ignores stale meta multiplier when rate changes', () => {
    const companyDefaults = ref(null)
    const jobs = ref<Record<string, unknown>[]>([])
    const noop = async () => {
      /* no-op */
    }

    const { createEntryFromRow } = useTimesheetEntryGrid(companyDefaults, jobs, noop, noop)

    const entry = createEntryFromRow({
      jobNumber: '12345',
      job_number: 12345,
      hours: 1,
      wageRate: 50,
      rate: '2.0',
      rateMultiplier: undefined,
      billable: true,
      description: 'Test',
      staffId: 'staff-1',
      date: '2024-05-01',
      meta: {
        rate_multiplier: 1,
        rate_type: 'Ord',
      },
    } as unknown as Parameters<typeof createEntryFromRow>[0])

    expect(entry.rateMultiplier).toBe(2)
    expect(entry.meta?.wage_rate_multiplier).toBe(2)
    expect(entry.wage).toBe(100)
  })
})
