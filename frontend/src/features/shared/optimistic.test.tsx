import { QueryClient, QueryClientProvider, useMutation, useQuery } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { useOptimisticRows } from './optimistic'

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
const row = (overrides: Partial<Row> = {}): Row => ({
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
function setup(initial: Row[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  queryClient.setQueryData<Doc>(KEY, { rows: initial })
  const invalidate = vi.fn()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  const hook = renderHook(
    () =>
      useOptimisticRows<Doc, Row>({
        queryKey: KEY,
        rows: (doc) => doc.rows,
        withRows: (doc, rows) => ({ ...doc, rows }),
        scopeId: 'grid:1',
        invalidate,
      }),
    { wrapper },
  )
  const rowsNow = () => queryClient.getQueryData<Doc>(KEY)!.rows
  return { ...hook, queryClient, invalidate, rowsNow, wrapper }
}

describe('optimistic grid queue', () => {
  it('shows an edit immediately and then canonical server pricing', async () => {
    const grid = setup([row()])
    const echo = deferred<Partial<Row>>()
    grid.result.current.patchRow('x', { unit_cost: '50.00' }, () => echo.promise, 'failed')
    expect(grid.rowsNow()[0]!.unit_cost).toBe('50.00')
    await act(async () => echo.resolve({ unit_cost: '50.00', total_cost: 50 }))
    expect(grid.rowsNow()[0]!.total_cost).toBe(50)
    expect(grid.invalidate).toHaveBeenCalledTimes(1)
  })

  it.each([false, true])(
    'keeps later choices over an earlier result (failure: %s)',
    async (fails) => {
      const grid = setup([row()])
      const first = deferred<Partial<Row>>()
      const second = deferred<Partial<Row>>()
      grid.result.current.patchRow('x', { unit_cost: '50.00' }, () => first.promise, 'failed')
      grid.result.current.patchRow('x', { unit_cost: '75.00' }, () => second.promise, 'failed')
      await act(async () => {
        if (fails) first.reject(new Error('no'))
        else first.resolve(row({ unit_cost: '50.00', total_cost: 50 }))
      })
      expect(grid.rowsNow()[0]!.unit_cost).toBe('75.00')
      expect(grid.invalidate).not.toHaveBeenCalled()
      await act(async () => second.resolve(row({ unit_cost: '75.00', total_cost: 75 })))
      expect(grid.rowsNow()[0]!.total_cost).toBe(75)
      expect(grid.invalidate).toHaveBeenCalledTimes(1)
    },
  )

  it.each([false, true])(
    'a refused second edit restores confirmed values (first failure: %s)',
    async (fails) => {
      const grid = setup([row()])
      const first = deferred<Partial<Row>>()
      const second = deferred<Partial<Row>>()
      grid.result.current.patchRow('x', { unit_cost: '50.00' }, () => first.promise, 'failed')
      grid.result.current.patchRow('x', { unit_cost: '75.00' }, () => second.promise, 'failed')
      await act(async () => {
        if (fails) first.reject(new Error('no'))
        else first.resolve(row({ unit_cost: '50.00', total_cost: 50 }))
      })
      await act(async () => second.reject(new Error('no')))
      expect(grid.rowsNow()[0]!.unit_cost).toBe(fails ? '10.00' : '50.00')
      expect(grid.rowsNow()[0]!.total_cost).toBe(fails ? 10 : 50)
    },
  )

  it('a queued delete remains hidden through the preceding edit echo, and restores that edit on refusal', async () => {
    const grid = setup([row(), row({ id: 'y' })])
    const patch = deferred<Partial<Row>>()
    const deletion = deferred<void>()
    grid.result.current.patchRow('x', { desc: 'edited' }, () => patch.promise, 'failed')
    grid.result.current.deleteRow('x', () => deletion.promise, 'failed')
    await act(async () => patch.resolve(row({ desc: 'edited' })))
    expect(grid.rowsNow().map((entry) => entry.id)).toEqual(['y'])
    await act(async () => deletion.reject(new Error('no')))
    expect(grid.rowsNow().map((entry) => entry.id)).toEqual(['x', 'y'])
    expect(grid.rowsNow()[0]!.desc).toBe('edited')
  })

  it('a refused delete preserves an edit on another row', async () => {
    const grid = setup([row(), row({ id: 'y' })])
    const deletion = deferred<void>()
    const patch = deferred<Partial<Row>>()
    grid.result.current.deleteRow('x', () => deletion.promise, 'failed')
    grid.result.current.patchRow('y', { desc: 'edited' }, () => patch.promise, 'failed')
    await act(async () => deletion.reject(new Error('no')))
    expect(grid.rowsNow().map((entry) => entry.id)).toEqual(['x', 'y'])
    expect(grid.rowsNow()[1]!.desc).toBe('edited')
    await act(async () => patch.resolve({ desc: 'edited' }))
  })

  it('includes an acknowledged creation in the drain and preserves its callback', async () => {
    const grid = setup([row()])
    const creation = deferred<void>()
    const patch = deferred<Partial<Row>>()
    const onCreated = vi.fn()
    grid.result.current.createRow(
      () => creation.promise,
      { onCreated, onFailed: vi.fn() },
      'failed',
    )
    grid.result.current.patchRow('x', { desc: 'edited' }, () => patch.promise, 'failed')
    await act(async () => creation.resolve())
    expect(onCreated).toHaveBeenCalledTimes(1)
    expect(grid.invalidate).not.toHaveBeenCalled()
    await act(async () => patch.resolve({ desc: 'edited' }))
    expect(grid.invalidate).toHaveBeenCalledTimes(1)
  })

  it('blocks refresh while queued and reconciles once after the last save', async () => {
    const grid = setup([row()])
    const serverRows = [row()]
    const read = vi.fn(async () => ({ rows: serverRows }))
    grid.invalidate.mockImplementation(() => grid.queryClient.invalidateQueries({ queryKey: KEY }))
    const query = renderHook(
      () =>
        useQuery({
          queryKey: KEY,
          queryFn: read,
          enabled: grid.result.current.canRefetch,
          staleTime: Infinity,
        }),
      { wrapper: grid.wrapper },
    )
    const first = deferred<Partial<Row>>()
    const second = deferred<Partial<Row>>()
    grid.result.current.patchRow('x', { desc: 'first' }, () => first.promise, 'failed')
    grid.result.current.patchRow('x', { desc: 'second' }, () => second.promise, 'failed')
    await act(async () => {
      await grid.queryClient.invalidateQueries({ queryKey: KEY })
    })
    expect(read).not.toHaveBeenCalled()
    await act(async () => first.resolve({ desc: 'first' }))
    expect(read).not.toHaveBeenCalled()
    expect(grid.rowsNow()[0]!.desc).toBe('second')
    serverRows[0] = row({ desc: 'second' })
    await act(async () => second.resolve({ desc: 'second' }))
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1))
    expect(query.result.current.data!.rows[0]!.desc).toBe('second')
  })

  it('serializes requests through the grid mutation scope', async () => {
    const grid = setup([row()])
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
    await act(async () => first.resolve())
    await waitFor(() => expect(calls).toEqual(['first', 'second']))
  })
})
