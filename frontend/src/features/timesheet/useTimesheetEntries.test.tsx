import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import type { TimesheetCostLineOut, TimesheetEntriesOut, TimesheetJobOut } from '@/api'
import { jobTimesheetEntriesRetrieveQueryKey } from '@/api'
import { server } from '@/test/msw'
import { useTimesheetEntries, type TimesheetCreateBody } from './useTimesheetEntries'

const STAFF_ID = 'staff-1'
const DATE = '2026-08-10'

function makeLine(overrides: Partial<TimesheetCostLineOut> = {}): TimesheetCostLineOut {
  return {
    id: 'line-1',
    kind: 'time',
    desc: 'Cutting',
    quantity: '2.000',
    unit_cost: '48.00',
    unit_rev: '120.00',
    ext_refs: {},
    meta: {
      staff_id: STAFF_ID,
      date: DATE,
      is_billable: true,
      wage_rate_multiplier: 1,
      bill_rate_multiplier: 1,
      created_from_timesheet: true,
    },
    created_at: '2026-08-10T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
    accounting_date: DATE,
    xero_time_id: null,
    xero_expense_id: null,
    xero_last_modified: null,
    xero_last_synced: null,
    approved: true,
    xero_pay_item: 'pay-ordinary',
    staff: STAFF_ID,
    entry_seq: 1,
    labour_subtype: 'subtype-workshop',
    total_cost: 96,
    total_rev: 240,
    job_id: 'job-1',
    job_number: 101,
    job_name: 'Fabricate frame',
    company_name: 'ABC Carpet Cleaning TEST IGNORE',
    ...overrides,
  }
}

function envelope(lines: TimesheetCostLineOut[]): TimesheetEntriesOut {
  return {
    cost_lines: lines,
    staff: { id: STAFF_ID, name: 'Wendy Workshop', first_name: 'Wendy', last_name: 'Workshop' },
    date: DATE,
    summary: {
      total_hours: 2,
      billable_hours: 2,
      non_billable_hours: 0,
      total_cost: 96,
      total_revenue: 240,
      entry_count: lines.length,
      scheduled_hours: 8,
    },
  }
}

const job: TimesheetJobOut = {
  id: 'job-2',
  job_number: 202,
  name: 'Emergency gate',
  company_name: 'ABC Carpet Cleaning TEST IGNORE',
  status: 'in_progress',
  labour_rates: [
    {
      id: 'rate-1',
      labour_subtype: 'subtype-workshop',
      labour_subtype_name: 'Workshop',
      is_workshop: true,
      charge_out_rate: '120.00',
    },
  ],
  has_actual_costset: true,
  leave_type: null,
  estimated_hours: null,
  default_xero_pay_item_id: 'pay-ordinary',
  default_xero_pay_item_name: 'Ordinary Time',
  shop_job: false,
  is_urgent: true,
}

function setup(lines: TimesheetCostLineOut[]) {
  // Stateful: mutation handlers update serverLines, so the settle-time
  // invalidation refetch returns post-write state like the real backend
  // (a static GET would "un-write" every mutation mid-test).
  const serverLines = [...lines]
  server.use(
    http.get('*/api/job/timesheet/entries/', () => HttpResponse.json(envelope(serverLines))),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  const hook = renderHook(() => useTimesheetEntries(STAFF_ID, DATE), { wrapper })
  return { ...hook, queryClient, serverLines }
}

// Read the CACHE, not the rendered hook value: optimistic writes land in the
// cache synchronously, one render before result.current catches up.
function cachedLines(hook: ReturnType<typeof setup>): TimesheetCostLineOut[] {
  const data = hook.queryClient.getQueryData<TimesheetEntriesOut>(
    jobTimesheetEntriesRetrieveQueryKey({ query: { staff_id: STAFF_ID, date: DATE } }),
  )
  return data?.cost_lines ?? []
}

const createBody: TimesheetCreateBody = {
  desc: 'Welding',
  quantity: '3.5',
  accounting_date: DATE,
  meta: {
    staff_id: STAFF_ID,
    date: DATE,
    is_billable: true,
    wage_rate_multiplier: 1,
    bill_rate_multiplier: 1.5,
    created_from_timesheet: true,
  },
}

describe('useTimesheetEntries', () => {
  it('loads the day envelope', async () => {
    const hook = setup([makeLine()])
    await waitFor(() => expect(hook.result.current.entriesQuery.isSuccess).toBe(true))
    expect(cachedLines(hook)).toHaveLength(1)
  })

  it('createLine inserts the response enriched with the picked job', async () => {
    const hook = setup([makeLine()])
    await waitFor(() => expect(hook.result.current.entriesQuery.isSuccess).toBe(true))
    const { job_id: _j, job_number: _n, job_name: _jn, company_name: _c, ...bareLine } = makeLine()
    server.use(
      http.post('*/api/job/jobs/job-2/cost_sets/actual/cost_lines/', () => {
        hook.serverLines.push(makeLine({ id: 'line-2', entry_seq: 2, job_number: 202 }))
        return HttpResponse.json({ ...bareLine, id: 'line-2', entry_seq: 2 }, { status: 201 })
      }),
    )
    const created: TimesheetCostLineOut[] = []
    hook.result.current.createLine(job, createBody, {
      onCreated: (line) => created.push(line),
      onFailed: () => {
        throw new Error('unexpected failure')
      },
    })
    await waitFor(() => expect(created).toHaveLength(1))
    expect(created[0]!.job_number).toBe(202)
    expect(created[0]!.job_name).toBe('Emergency gate')
    expect(cachedLines(hook).some((line) => line.id === 'line-2')).toBe(true)
  })

  it('patchLine applies optimistically and merges the repriced echo', async () => {
    const hook = setup([makeLine()])
    await waitFor(() => expect(hook.result.current.entriesQuery.isSuccess).toBe(true))
    const { job_id: _j, job_number: _n, job_name: _jn, company_name: _c, ...bareLine } = makeLine()
    server.use(
      http.patch('*/api/job/cost_lines/line-1/', () => {
        hook.serverLines[0] = makeLine({
          quantity: '4.000',
          unit_cost: '96.00',
          xero_pay_item: 'pay-double',
          total_cost: 384,
        })
        return HttpResponse.json({
          ...bareLine,
          quantity: '4.000',
          unit_cost: '96.00',
          xero_pay_item: 'pay-double',
          total_cost: 384,
        })
      }),
    )
    hook.result.current.patchLine('line-1', {
      quantity: '4',
      meta: { ...makeLine().meta, wage_rate_multiplier: 2 },
    })
    // Optimistic value first.
    expect(cachedLines(hook)[0]!.quantity).toBe('4')
    // Echo merge: server pricing outputs land, job identity survives.
    await waitFor(() => expect(cachedLines(hook)[0]!.xero_pay_item).toBe('pay-double'))
    expect(cachedLines(hook)[0]!.total_cost).toBe(384)
    expect(cachedLines(hook)[0]!.job_number).toBe(101)
  })

  it('a failed patch rolls back only its own fields and toasts', async () => {
    const hook = setup([makeLine()])
    await waitFor(() => expect(hook.result.current.entriesQuery.isSuccess).toBe(true))
    server.use(
      http.patch('*/api/job/cost_lines/line-1/', () =>
        HttpResponse.json({ detail: 'no' }, { status: 400 }),
      ),
    )
    hook.result.current.patchLine('line-1', { desc: 'rejected description' })
    expect(cachedLines(hook)[0]!.desc).toBe('rejected description')
    await waitFor(() => expect(cachedLines(hook)[0]!.desc).toBe('Cutting'))
  })

  it('a failed delete reinserts only its line', async () => {
    const hook = setup([makeLine(), makeLine({ id: 'line-2', entry_seq: 2 })])
    await waitFor(() => expect(hook.result.current.entriesQuery.isSuccess).toBe(true))
    server.use(
      http.delete('*/api/job/cost_lines/line-1/delete/', () =>
        HttpResponse.json({ detail: 'no' }, { status: 400 }),
      ),
    )
    hook.result.current.deleteLine('line-1')
    expect(cachedLines(hook).map((line) => line.id)).toEqual(['line-2'])
    await waitFor(() =>
      expect(cachedLines(hook).map((line) => line.id)).toEqual(['line-1', 'line-2']),
    )
  })

  it('approveLine merges the approval echo', async () => {
    const hook = setup([makeLine({ approved: false })])
    await waitFor(() => expect(hook.result.current.entriesQuery.isSuccess).toBe(true))
    const { job_id: _j, job_number: _n, job_name: _jn, company_name: _c, ...bareLine } = makeLine()
    server.use(
      http.post('*/api/job/cost_lines/line-1/approve/', () => {
        hook.serverLines[0] = makeLine({ approved: true })
        return HttpResponse.json({
          success: true,
          message: 'approved',
          remaining_quantity: null,
          line: { ...bareLine, approved: true },
        })
      }),
    )
    hook.result.current.approveLine('line-1')
    await waitFor(() => expect(cachedLines(hook)[0]!.approved).toBe(true))
  })
})
