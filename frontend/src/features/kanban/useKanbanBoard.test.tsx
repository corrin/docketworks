import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw/http'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import type { KanbanJobOut } from '@/api'
import { server } from '@/test/msw'

import { useKanbanBoard } from './useKanbanBoard'

const COLUMN_URL = '*/api/job/jobs/fetch-by-column/:columnId/'
const STATUS_VALUES_URL = '*/api/job/jobs/status-values/'
const SEARCH_URL = '*/api/job/jobs/advanced-search/'

function job(id: string, statusKey: string): KanbanJobOut {
  return {
    id,
    job_number: 100,
    name: `Job ${id}`,
    description: null,
    status: statusKey,
    status_key: statusKey,
    priority: 1,
    company_name: 'ABC Carpet Cleaning TEST IGNORE',
    person_name: '',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
    created_by_id: null,
    delivery_date: null,
    people: [],
    fully_invoiced: false,
    is_urgent: false,
    max_people: 1,
    min_people: 1,
    over_budget: false,
    paid: false,
    quote_revenue: 0,
    rejected_flag: false,
    shop_job: statusKey === 'special',
    speed_quality_tradeoff: 'balanced',
    time_and_materials_revenue: 0,
  }
}

function renderBoard(searchTerm: string, found: KanbanJobOut[]) {
  server.use(
    http.get(COLUMN_URL, () =>
      HttpResponse.json({
        success: true,
        error: null,
        jobs: [],
        total: 0,
        filtered_count: 0,
        has_more: false,
      }),
    ),
    http.get(STATUS_VALUES_URL, () => HttpResponse.json({ statuses: {}, tooltips: {} })),
    http.get(SEARCH_URL, () =>
      HttpResponse.json({ success: true, jobs: found, total: found.length }),
    ),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderHook(() => useKanbanBoard(searchTerm, { movePendingRef: { current: false } }), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  })
}

describe('useKanbanBoard search', () => {
  it('shows a special job a search finds in a Special column after the office columns', async () => {
    const hook = renderBoard('general', [job('general-work', 'special'), job('quote', 'draft')])

    await waitFor(() => expect(hook.result.current.columns.at(-1)?.id).toBe('special'))
    const special = hook.result.current.columns.at(-1)
    expect(special?.jobs.map((found) => found.id)).toEqual(['general-work'])
    expect(special?.label).toBe('Special')
  })

  it('adds no Special column when the search finds no special job', async () => {
    const hook = renderBoard('quote', [job('quote', 'draft')])

    await waitFor(() =>
      expect(
        hook.result.current.columns.find((column) => column.id === 'draft')?.jobs,
      ).toHaveLength(1),
    )
    expect(hook.result.current.columns.map((column) => column.id)).not.toContain('special')
  })
})
