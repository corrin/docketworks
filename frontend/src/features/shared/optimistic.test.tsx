import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { restoreDeletedRow, useOptimisticRows } from './optimistic'

interface Row {
  id: string
  desc: string
  unit_cost: string
  total_cost: number
}
interface Doc {
  rows: Row[]
}

const KEY = ['grid']
const row = (overrides: Partial<Row>): Row => ({
  id: 'x',
  desc: 'Line',
  unit_cost: '10.00',
  total_cost: 10,
  ...overrides,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function setup(rows: Row[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  queryClient.setQueryData<Doc>(KEY, { rows })
  const invalidate = vi.fn()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  const hook = renderHook(
    () =>
      useOptimisticRows<Doc, Row>({
        queryKey: KEY,
        rows: (doc) => doc.rows,
        withRows: (doc, next) => ({ ...doc, rows: next }),
        scopeId: 'grid:1',
        invalidate,
      }),
    { wrapper },
  )
  const rowsNow = () => queryClient.getQueryData<Doc>(KEY)!.rows
  return { ...hook, queryClient, invalidate, rowsNow, wrapper }
}

describe('useOptimisticRows.patchRow', () => {
  it('shows the display at once, then the echo, and invalidates once', async () => {
    const grid = setup([row({})])
    const echo = deferred<Partial<Row>>()

    grid.result.current.patchRow('x', { unit_cost: '50.00' }, () => echo.promise, 'failed')

    expect(grid.rowsNow()[0]!.unit_cost).toBe('50.00')
    await act(async () => echo.resolve({ unit_cost: '50.00', total_cost: 50 }))
    await waitFor(() => expect(grid.rowsNow()[0]!.total_cost).toBe(50))
    expect(grid.invalidate).toHaveBeenCalledTimes(1)
  })

  it('a refusal restores only the fields still showing the rejected value', async () => {
    // The restoreRejectedPatch rule: an edit made after the rejected write survives it.
    const grid = setup([row({})])
    const refusal = deferred<void>()

    grid.result.current.patchRow(
      'x',
      { unit_cost: '50.00', desc: 'typo' },
      () => refusal.promise,
      'failed',
    )
    grid.queryClient.setQueryData<Doc>(KEY, {
      rows: [row({ unit_cost: '50.00', desc: 'later edit' })],
    })
    await act(async () => refusal.reject(new Error('no')))

    await waitFor(() => expect(grid.rowsNow()[0]!.unit_cost).toBe('10.00'))
    expect(grid.rowsNow()[0]!.desc).toBe('later edit')
  })
})

describe('useOptimisticRows.deleteRow', () => {
  it('a refused delete puts the row back at its own index and nothing else', async () => {
    const grid = setup([row({ id: 'x' }), row({ id: 'y' })])
    const refusal = deferred<void>()

    grid.result.current.deleteRow('x', () => refusal.promise, 'failed')
    expect(grid.rowsNow().map((entry) => entry.id)).toEqual(['y'])
    // Another row changes while the delete is in flight; the restore must keep that.
    grid.queryClient.setQueryData<Doc>(KEY, { rows: [row({ id: 'y', desc: 'edited' })] })
    await act(async () => refusal.reject(new Error('no')))

    await waitFor(() => expect(grid.rowsNow().map((entry) => entry.id)).toEqual(['x', 'y']))
    expect(grid.rowsNow()[1]!.desc).toBe('edited')
  })
})

describe('restoreDeletedRow', () => {
  it('re-inserts only the deleted row at its index, not the whole snapshot', () => {
    const current = [row({ id: 'x', unit_cost: '12.00' })]
    const snapshot = [row({ id: 'x', unit_cost: 'rejected' }), row({ id: 'y' })]

    const restored = restoreDeletedRow(current, snapshot, 'y')

    expect(restored.map((entry) => entry.id)).toEqual(['x', 'y'])
    expect(restored[0]!.unit_cost).toBe('12.00')
  })
})

describe('serialized', () => {
  it('two writes on one grid reach the server in order, the second after the first settles', async () => {
    const grid = setup([row({})])
    const first = deferred<void>()
    const calls: string[] = []
    const mutation = renderHook(
      () =>
        useMutation(
          grid.result.current.serialized({
            mutationFn: async (name: string) => {
              calls.push(name)
              if (name === 'first') await first.promise
            },
          }),
        ),
      { wrapper: grid.wrapper },
    )

    void mutation.result.current.mutateAsync('first')
    void mutation.result.current.mutateAsync('second')
    await waitFor(() => expect(calls).toEqual(['first']))
    expect(calls).not.toContain('second')
    await act(async () => first.resolve())
    await waitFor(() => expect(calls).toEqual(['first', 'second']))
  })
})
