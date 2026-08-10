import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { useRef, type ReactNode } from 'react'
import { toast } from 'sonner'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  jobJobsAdvancedSearchRetrieveQueryKey,
  type DataVersions,
  type FetchJobsByColumnResponse,
  type KanbanChangesResponse,
  type KanbanColumnJobOut,
} from '@/api'
import { dataVersionsQueryOptions } from '@/features/shell'
import { server } from '@/test/msw'

import { columnQueryKey, COLUMN_MAX_JOBS } from './boardCache'
import { OFFICE_COLUMN_IDS } from './columns'
import { useKanbanBoard } from './useKanbanBoard'
import { useKanbanReconciliation } from './useKanbanReconciliation'

const CHANGES_URL = '*/api/job/jobs/kanban-changes/'
const VERSIONS_URL = '*/api/data-versions/'
const COLUMN_URL = '*/api/job/jobs/fetch-by-column/:columnId/'
const STATUS_VALUES_URL = '*/api/job/jobs/status-values/'
const REORDER_URL = '*/api/job/jobs/:jobId/reorder/'
const SEARCH_URL = '*/api/job/jobs/advanced-search/'

/** The opaque cursor shape the backend emits (updated_at|created_at|count). */
const versionAt = (marker: string): string =>
  `2026-08-10T0${marker}:00:00.000000+00:00|2026-08-01T00:00:00.000000+00:00|7`

function versions(overrides: Partial<DataVersions> = {}): DataVersions {
  return {
    stock: 'stock-1',
    kanban: versionAt('1'),
    kanban_related: 'related-1',
    crm_calls: 'crm-1',
    ...overrides,
  }
}

function card(
  id: string,
  statusKey: string,
  priority: number,
  overrides: Partial<KanbanColumnJobOut> = {},
): KanbanColumnJobOut {
  return {
    id,
    job_number: 100,
    name: `Job ${id}`,
    description: null,
    status: statusKey,
    status_key: statusKey,
    priority,
    company_name: 'ABC Carpet Cleaning TEST IGNORE',
    person_name: '',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
    created_by_id: null,
    delivery_date: null,
    people: [],
    badge_color: 'grey',
    badge_label: 'Draft',
    fully_invoiced: false,
    is_urgent: false,
    max_people: 1,
    min_people: 1,
    over_budget: false,
    paid: false,
    quote_revenue: 0,
    rejected_flag: false,
    shop_job: false,
    speed_quality_tradeoff: 'balanced',
    time_and_materials_revenue: 0,
    ...overrides,
  }
}

function column(
  jobs: KanbanColumnJobOut[],
  overrides: Partial<FetchJobsByColumnResponse> = {},
): FetchJobsByColumnResponse {
  return {
    success: true,
    error: null,
    jobs,
    total: jobs.length,
    filtered_count: jobs.length,
    has_more: false,
    ...overrides,
  }
}

function changes(overrides: Partial<KanbanChangesResponse> = {}): KanbanChangesResponse {
  return {
    success: true,
    jobs: [],
    removed_job_ids: [],
    full_refresh_required: false,
    ...overrides,
  }
}

/** A promise the test releases by hand. Promise.withResolvers is ES2024; the lib here is ES2023. */
function deferred(): { promise: Promise<void>; resolve: () => void } {
  let settle: (() => void) | undefined
  const promise = new Promise<void>((resolve) => {
    settle = resolve
  })
  return {
    promise,
    resolve: () => {
      if (!settle) throw new Error('deferred(): the promise executor did not run')
      settle()
    },
  }
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function wrapperFor(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

/** Cached ids per column, in render order — the only thing the board renders from. */
function cachedIds(queryClient: QueryClient, columnId: string): string[] {
  const data = queryClient.getQueryData<FetchJobsByColumnResponse>(columnQueryKey(columnId))
  return (data?.jobs ?? []).map((job) => job.id)
}

/** Every column holding the job — an id appearing twice is the duplicate-card bug. */
function columnsHolding(queryClient: QueryClient, jobId: string): string[] {
  return OFFICE_COLUMN_IDS.filter((columnId) => cachedIds(queryClient, columnId).includes(jobId))
}

function invalidatedColumns(queryClient: QueryClient): string[] {
  return OFFICE_COLUMN_IDS.filter(
    (columnId) => queryClient.getQueryState(columnQueryKey(columnId))?.isInvalidated === true,
  )
}

interface ReconcileHarness {
  queryClient: QueryClient
  isDraggingRef: { current: boolean }
  movePendingRef: { current: boolean }
  reconcile: () => Promise<void>
  /** Publish a new poll result, exactly as the interval refetch would. */
  poll: (next: DataVersions) => void
  changesRequests: string[]
}

/**
 * The loop over pre-seeded column caches: the columns are written directly
 * rather than fetched, because these tests are about what a diff does to a
 * cache, not about how the cache was filled.
 */
async function setupLoop(
  seeded: Partial<Record<string, FetchJobsByColumnResponse>>,
  responder: () => Response,
  searchTerm = '',
): Promise<ReconcileHarness> {
  const queryClient = makeClient()
  for (const [columnId, data] of Object.entries(seeded)) {
    if (data) queryClient.setQueryData(columnQueryKey(columnId), data)
  }
  queryClient.setQueryData(dataVersionsQueryOptions().queryKey, versions())

  const changesRequests: string[] = []
  server.use(
    http.get(VERSIONS_URL, () => HttpResponse.json(versions())),
    http.get(CHANGES_URL, ({ request }) => {
      changesRequests.push(new URL(request.url).searchParams.get('after') ?? '')
      return responder()
    }),
    http.get(SEARCH_URL, () => HttpResponse.json({ success: true, jobs: [], total: 0 })),
  )

  const refs = { isDraggingRef: { current: false }, movePendingRef: { current: false } }
  const hook = renderHook(
    () =>
      useKanbanReconciliation({
        isDraggingRef: refs.isDraggingRef,
        movePendingRef: refs.movePendingRef,
        searchTerm,
      }),
    { wrapper: wrapperFor(queryClient) },
  )

  // The mount pass seeds the cursor from the boot value and applies nothing.
  await waitFor(() => expect(changesRequests).toHaveLength(0))

  return {
    queryClient,
    ...refs,
    reconcile: () => hook.result.current.reconcile(),
    poll: (next) => queryClient.setQueryData(dataVersionsQueryOptions().queryKey, next),
    changesRequests,
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useKanbanReconciliation', () => {
  it('seeds the cursor from the boot value and asks for nothing until a version moves', async () => {
    const loop = await setupLoop({ draft: column([card('a', 'draft', 90)]) }, () =>
      HttpResponse.json(changes()),
    )

    await loop.reconcile()

    expect(loop.changesRequests).toEqual([])
  })

  it('sends the cursor it was seeded with, then advances it', async () => {
    const loop = await setupLoop({ draft: column([card('a', 'draft', 90)]) }, () =>
      HttpResponse.json(changes()),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()
    loop.poll(versions({ kanban: versionAt('3') }))
    await loop.reconcile()

    expect(loop.changesRequests).toEqual([versionAt('1'), versionAt('2')])
  })

  it('inserts a changed card at its descending-priority slot', async () => {
    const loop = await setupLoop(
      {
        draft: column([card('a', 'draft', 90), card('b', 'draft', 70), card('c', 'draft', 50)]),
      },
      () => HttpResponse.json(changes({ jobs: [card('new', 'draft', 80)] })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['a', 'new', 'b', 'c'])
  })

  it('re-slots a card already in the column without duplicating it', async () => {
    const loop = await setupLoop(
      {
        draft: column([card('a', 'draft', 90), card('b', 'draft', 70), card('c', 'draft', 50)]),
      },
      () => HttpResponse.json(changes({ jobs: [card('c', 'draft', 95)] })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['c', 'a', 'b'])
    expect(columnsHolding(loop.queryClient, 'c')).toEqual(['draft'])
  })

  it('moves a card between columns, leaving it in exactly one', async () => {
    const loop = await setupLoop(
      {
        draft: column([card('a', 'draft', 90), card('b', 'draft', 70)]),
        in_progress: column([card('x', 'in_progress', 80), card('y', 'in_progress', 40)]),
      },
      () => HttpResponse.json(changes({ jobs: [card('b', 'in_progress', 60)] })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['a'])
    expect(cachedIds(loop.queryClient, 'in_progress')).toEqual(['x', 'b', 'y'])
    expect(columnsHolding(loop.queryClient, 'b')).toEqual(['in_progress'])
  })

  it('drops a change that lands below a truncated column window', async () => {
    const window = Array.from({ length: COLUMN_MAX_JOBS }, (_, index) =>
      card(`w${index}`, 'in_progress', 1000 - index),
    )
    const loop = await setupLoop(
      {
        draft: column([card('b', 'draft', 70)]),
        in_progress: column(window, { has_more: true, total: 640 }),
      },
      // Priority 12 sorts below the last loaded card (801), so this card
      // lives beyond the 200-row window the column actually holds.
      () => HttpResponse.json(changes({ jobs: [card('b', 'in_progress', 12)] })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(columnsHolding(loop.queryClient, 'b')).toEqual([])
    expect(cachedIds(loop.queryClient, 'in_progress')).toHaveLength(COLUMN_MAX_JOBS)
  })

  it('keeps a change that lands inside a truncated column window', async () => {
    const loop = await setupLoop(
      {
        in_progress: column([card('x', 'in_progress', 90), card('y', 'in_progress', 40)], {
          has_more: true,
          total: 640,
        }),
      },
      () => HttpResponse.json(changes({ jobs: [card('b', 'in_progress', 60)] })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(cachedIds(loop.queryClient, 'in_progress')).toEqual(['x', 'b', 'y'])
  })

  it('removes a card whose new status has no column on the office board', async () => {
    const loop = await setupLoop(
      { draft: column([card('a', 'draft', 90), card('b', 'draft', 70)]) },
      () => HttpResponse.json(changes({ jobs: [card('b', 'archived', 70)] })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['a'])
    expect(columnsHolding(loop.queryClient, 'b')).toEqual([])
  })

  it('applies removed_job_ids', async () => {
    const loop = await setupLoop(
      {
        draft: column([card('a', 'draft', 90), card('b', 'draft', 70)]),
        approved: column([card('c', 'approved', 30)]),
      },
      () => HttpResponse.json(changes({ removed_job_ids: ['b', 'c'] })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['a'])
    expect(cachedIds(loop.queryClient, 'approved')).toEqual([])
  })

  it('invalidates every column on full_refresh_required', async () => {
    const loop = await setupLoop(
      {
        draft: column([card('a', 'draft', 90)]),
        approved: column([card('c', 'approved', 30)]),
      },
      () => HttpResponse.json(changes({ full_refresh_required: true })),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(invalidatedColumns(loop.queryClient)).toEqual(['draft', 'approved'])
  })

  it('invalidates every column when kanban_related moves, without fetching a diff', async () => {
    const loop = await setupLoop({ draft: column([card('a', 'draft', 90)]) }, () =>
      HttpResponse.json(changes()),
    )

    loop.poll(versions({ kanban_related: 'related-2' }))
    await loop.reconcile()

    expect(loop.changesRequests).toEqual([])
    expect(invalidatedColumns(loop.queryClient)).toEqual(['draft'])
  })

  it('invalidates the search query when a diff lands while a search is active', async () => {
    const loop = await setupLoop(
      { draft: column([card('a', 'draft', 90)]) },
      () => HttpResponse.json(changes({ jobs: [card('a', 'draft', 95)] })),
      'gate',
    )
    const searchKey = jobJobsAdvancedSearchRetrieveQueryKey({ query: { q: 'gate' } })
    loop.queryClient.setQueryData(searchKey, { success: true, jobs: [], total: 0 })

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(loop.queryClient.getQueryState(searchKey)?.isInvalidated).toBe(true)
  })

  it('leaves the search query alone when the diff is empty', async () => {
    const loop = await setupLoop(
      { draft: column([card('a', 'draft', 90)]) },
      () => HttpResponse.json(changes()),
      'gate',
    )
    const searchKey = jobJobsAdvancedSearchRetrieveQueryKey({ query: { q: 'gate' } })
    loop.queryClient.setQueryData(searchKey, { success: true, jobs: [], total: 0 })

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(loop.queryClient.getQueryState(searchKey)?.isInvalidated).toBe(false)
  })

  it('defers the whole tick while a drag is in flight, keeping the cursor put', async () => {
    const loop = await setupLoop(
      { draft: column([card('a', 'draft', 90), card('b', 'draft', 70)]) },
      () => HttpResponse.json(changes({ jobs: [card('b', 'draft', 95)] })),
    )

    loop.isDraggingRef.current = true
    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(loop.changesRequests).toEqual([])
    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['a', 'b'])

    // Released: the deferred change arrives on the next tick, asked for from
    // the SAME cursor — the feed is cursor-idempotent, so nothing is lost.
    loop.isDraggingRef.current = false
    await loop.reconcile()

    expect(loop.changesRequests).toEqual([versionAt('1')])
    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['b', 'a'])
  })

  it('defers the tick while a move is persisting', async () => {
    const loop = await setupLoop({ draft: column([card('a', 'draft', 90)]) }, () =>
      HttpResponse.json(changes({ jobs: [card('a', 'archived', 90)] })),
    )

    loop.movePendingRef.current = true
    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(loop.changesRequests).toEqual([])
    expect(cachedIds(loop.queryClient, 'draft')).toEqual(['a'])
  })

  it('toasts once per failure streak and retries from the same cursor', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    const loop = await setupLoop({ draft: column([card('a', 'draft', 90)]) }, () =>
      HttpResponse.json({ message: 'kanban feed is down' }, { status: 503 }),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()
    loop.poll(versions({ kanban: versionAt('3') }))
    await loop.reconcile()
    loop.poll(versions({ kanban: versionAt('4') }))
    await loop.reconcile()

    expect(loop.changesRequests).toEqual([versionAt('1'), versionAt('1'), versionAt('1')])
    expect(toastError).toHaveBeenCalledTimes(1)
    expect(toastError).toHaveBeenCalledWith('kanban feed is down')
  })

  it('toasts again after the poll recovers and breaks a second time', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    let healthy = false
    const loop = await setupLoop({ draft: column([card('a', 'draft', 90)]) }, () =>
      healthy
        ? HttpResponse.json(changes())
        : HttpResponse.json({ message: 'down' }, { status: 503 }),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()
    healthy = true
    await loop.reconcile()
    healthy = false
    loop.poll(versions({ kanban: versionAt('3') }))
    await loop.reconcile()

    expect(toastError).toHaveBeenCalledTimes(2)
  })

  it('treats a rejected cursor as a full refresh and reseeds from the poll', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    const loop = await setupLoop({ draft: column([card('a', 'draft', 90)]) }, () =>
      HttpResponse.json({ message: 'Invalid Kanban version' }, { status: 400 }),
    )

    loop.poll(versions({ kanban: versionAt('2') }))
    await loop.reconcile()

    expect(invalidatedColumns(loop.queryClient)).toEqual(['draft'])
    expect(toastError).not.toHaveBeenCalled()

    // Reseeded: the next pass asks from the version the 400 arrived under,
    // not from the cursor the server just refused.
    loop.poll(versions({ kanban: versionAt('3') }))
    await loop.reconcile()

    expect(loop.changesRequests).toEqual([versionAt('1'), versionAt('2')])
  })
})

/**
 * The Task-2 race, reproduced end to end.
 *
 * Dropping into a column whose first-ever fetch is still in flight: the
 * reorder's onSuccess invalidation rides that in-flight GET (query-core
 * reuses a pending initial fetch rather than restarting it — Query.fetch only
 * honours cancelRefetch once state.data exists), the GET was issued before
 * the server saw the move, and it resolves without the moved card. Nothing
 * re-triggers, so before this loop existed the card was in no column at all.
 */
describe('reconciliation closes the in-flight-first-fetch reorder race', () => {
  it('restores a card the stale initial fetch dropped', async () => {
    const queryClient = makeClient()
    queryClient.setQueryData(dataVersionsQueryOptions().queryKey, versions())

    const moved = card('moved', 'draft', 70)
    const targetFetch = deferred()

    server.use(
      http.get(VERSIONS_URL, () => HttpResponse.json(versions())),
      http.get(STATUS_VALUES_URL, () =>
        HttpResponse.json({ success: true, statuses: {}, tooltips: {} }),
      ),
      http.get(COLUMN_URL, async ({ params }) => {
        const columnId = String(params.columnId)
        if (columnId === 'draft') {
          return HttpResponse.json(column([card('other', 'draft', 90), moved]))
        }
        if (columnId === 'in_progress') {
          // The first-ever fetch of the destination column, deliberately
          // still open when the reorder POST resolves — and answering with
          // pre-move data when it finally does.
          await targetFetch.promise
          return HttpResponse.json(column([card('resident', 'in_progress', 80)]))
        }
        return HttpResponse.json(column([]))
      }),
      http.post(REORDER_URL, () => HttpResponse.json({ success: true })),
      http.get(CHANGES_URL, () =>
        HttpResponse.json(changes({ jobs: [card('moved', 'in_progress', 60)] })),
      ),
    )

    const hook = renderHook(
      () => {
        const board = useKanbanBoard('')
        const isDraggingRef = useRef(false)
        const reconciliation = useKanbanReconciliation({
          isDraggingRef,
          movePendingRef: board.movePendingRef,
          searchTerm: board.searchTerm,
        })
        return { board, reconciliation }
      },
      { wrapper: wrapperFor(queryClient) },
    )

    await waitFor(() => expect(cachedIds(queryClient, 'draft')).toEqual(['other', 'moved']))
    expect(queryClient.getQueryData(columnQueryKey('in_progress'))).toBeUndefined()

    hook.result.current.board.moveJob({ jobId: 'moved', status: 'in_progress' })
    await waitFor(() => expect(hook.result.current.board.movePendingRef.current).toBe(false))

    // The invalidation had nothing to restart, so the stale GET is what lands.
    targetFetch.resolve()
    await waitFor(() => expect(cachedIds(queryClient, 'in_progress')).toEqual(['resident']))
    // The bug in its raw form: the card is on no board column.
    expect(columnsHolding(queryClient, 'moved')).toEqual([])

    queryClient.setQueryData(
      dataVersionsQueryOptions().queryKey,
      versions({ kanban: versionAt('2') }),
    )
    await hook.result.current.reconciliation.reconcile()

    expect(columnsHolding(queryClient, 'moved')).toEqual(['in_progress'])
    expect(cachedIds(queryClient, 'in_progress')).toEqual(['resident', 'moved'])
  })
})
