import { describe, expect, it } from 'vitest'

import type { CostLineOut } from '@/api'
import { mergeEchoFields, restoreDeletedLine } from './useCostLines'

const line = (overrides: Partial<CostLineOut>): CostLineOut => ({
  accounting_date: '2026-08-09',
  approved: false,
  created_at: '2026-08-09T00:00:00Z',
  desc: 'Line',
  entry_seq: null,
  ext_refs: {},
  id: 'line-1',
  kind: 'material',
  labour_subtype: null,
  meta: {},
  quantity: '1.000',
  staff: null,
  total_cost: 10,
  total_rev: 12,
  unit_cost: '10.00',
  unit_rev: '12.00',
  updated_at: '2026-08-09T00:00:00Z',
  xero_expense_id: null,
  xero_last_modified: null,
  xero_last_synced: null,
  xero_pay_item: null,
  xero_time_id: null,
  ...overrides,
})

describe('mergeEchoFields', () => {
  it('applies only the patched fields from the echo, keeping later optimistic edits', () => {
    // PATCH A (unit_cost) echoes while optimistic PATCH B (desc) is showing:
    // A's echo must not clobber B's desc.
    const current = line({ id: 'x', desc: 'B optimistic', unit_cost: '99.00' })
    const echo = line({ id: 'x', desc: 'old desc', unit_cost: '50.00', total_cost: 50 })

    const merged = mergeEchoFields(current, echo, { unit_cost: '50.00' })

    expect(merged.unit_cost).toBe('50.00')
    expect(merged.desc).toBe('B optimistic')
    // Server-computed line totals ride along — they belong to no field.
    expect(merged.total_cost).toBe(50)
    expect(merged.updated_at).toBe(echo.updated_at)
  })
})

describe('restoreDeletedLine', () => {
  it('re-inserts only the deleted line at its index, not the whole snapshot', () => {
    const lineX = line({ id: 'x', unit_rev: 'rejected-optimistic' })
    const snapshotX = line({ id: 'x', unit_rev: '12.00' })
    const lineY = line({ id: 'y' })
    // The current cache has X already rolled back by its own PATCH failure.
    const current = [line({ id: 'x', unit_rev: '12.00' })]
    const snapshot = [snapshotX, lineY]
    void lineX

    const restored = restoreDeletedLine(current, snapshot, 'y')

    expect(restored.map((entry) => entry.id)).toEqual(['x', 'y'])
    // X keeps its current (rolled-back) value, not the snapshot's state.
    expect(restored[0]!.unit_rev).toBe('12.00')
  })
})
