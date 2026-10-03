// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { CostLineOut } from '@/api'
import { useOptimisticRows } from '@/features/shared/optimistic'

const line = (overrides: Partial<CostLineOut>): CostLineOut => ({
  accounting_date: '2026-08-09',
  approved: false,
  managed_by: null,
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

function grid(initial: CostLineOut[]) {
  const client = new QueryClient()
  const key = ['cost-line-regressions']
  client.setQueryData(key, initial)
  const hook = renderHook(
    () =>
      useOptimisticRows<CostLineOut[], CostLineOut>({
        queryKey: key,
        scopeId: 'cost-line-regressions',
        rows: (rows) => rows,
        withRows: (_, rows) => rows,
        invalidate: vi.fn(),
      }),
    {
      wrapper: ({ children }: { children: ReactNode }) =>
        createElement(QueryClientProvider, { client }, children),
    },
  )
  return { hook, rows: () => client.getQueryData<CostLineOut[]>(key)! }
}

describe('cost-line reconciliation through the shared grid', () => {
  it('keeps later optimistic edits when an earlier price echo arrives', async () => {
    // PATCH A (unit_cost) echoes while optimistic PATCH B (desc) is showing:
    // A's echo must not clobber B's desc.
    const state = grid([line({ id: 'x', desc: 'old desc' })])
    const echo = line({ id: 'x', desc: 'old desc', unit_cost: '50.00', total_cost: 50 })

    let resolvePrice!: (value: CostLineOut) => void
    let resolveDescription!: (value: Partial<CostLineOut>) => void
    const price = new Promise<CostLineOut>((resolve) => {
      resolvePrice = resolve
    })
    const description = new Promise<Partial<CostLineOut>>((resolve) => {
      resolveDescription = resolve
    })
    state.hook.result.current.patchRow('x', { unit_cost: '50.00' }, () => price, 'failed')
    state.hook.result.current.patchRow('x', { desc: 'B optimistic' }, () => description, 'failed')
    await act(async () => resolvePrice(echo))
    const merged = state.rows()[0]!

    expect(merged.unit_cost).toBe('50.00')
    expect(merged.desc).toBe('B optimistic')
    // Server-computed line totals ride along — they belong to no field.
    expect(merged.total_cost).toBe(50)
    expect(merged.updated_at).toBe(echo.updated_at)
    await act(async () => resolveDescription({ desc: 'B optimistic' }))
  })
})

describe('cost-line delete rollback through the shared grid', () => {
  it('re-inserts only the deleted line, keeping another line’s successful price edit', async () => {
    // GPT: the delete snapshot predates another row's successful edit. Restoring
    // the entire snapshot must fail the assertion on that newer price.
    const snapshotX = line({ id: 'x', unit_rev: '12.00' })
    const lineY = line({ id: 'y' })
    const state = grid([snapshotX, lineY])
    let refuse!: (error: Error) => void
    const deletion = new Promise<void>((_, reject) => {
      refuse = reject
    })
    state.hook.result.current.deleteRow('y', () => deletion, 'failed')
    await act(async () =>
      state.hook.result.current.patchRow(
        'x',
        { unit_rev: '18.00' },
        async () => ({ unit_rev: '18.00' }),
        'failed',
      ),
    )
    await act(async () => refuse(new Error('refused')))
    const restored = state.rows()

    expect(restored.map((entry) => entry.id)).toEqual(['x', 'y'])
    expect(restored[0]!.unit_rev).toBe('18.00')
  })
})
