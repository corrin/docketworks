/**
 * Everything the office board renders, assembled from the query cache.
 *
 * Six per-column queries, one status-values query, one search query. There is
 * no store and no client-side sorting: the server returns each column in
 * `-priority` order and that array order is the render order, so "the top
 * card" means "the first element the server sent" at every layer.
 *
 * Reorders deliberately do NOT invalidate on success — unlike useCostLines,
 * which invalidates on settle because the server owns the derived totals.
 * Here the optimistic array already IS the new order, and a refetch would
 * make every drag flash back through the old order. Server truth arrives via
 * the kanban-changes reconciliation feed instead.
 */
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobJobsAdvancedSearchRetrieveOptions,
  jobJobsFetchByColumnRetrieveOptions,
  jobJobsReorderCreateMutation,
  jobJobsStatusValuesRetrieveOptions,
} from '@/api'
import type { KanbanJobOut } from '@/api'

import {
  applyJobUpsert,
  columnFetchOptions,
  columnQueryKey,
  findColumnJob,
  restoreSnapshot,
  snapshotColumns,
  type Placement,
} from './boardCache'
import { fallbackColumnLabel, OFFICE_COLUMN_IDS, type OfficeColumnId } from './columns'

export interface KanbanColumnView {
  id: OfficeColumnId
  label: string
  tooltip: string
  /** Render order, already filtered — never re-sort this. */
  jobs: KanbanJobOut[]
  /** v1's jobCountDisplay: "N", or "X of Y" when filtered or truncated. */
  countDisplay: string
  isLoading: boolean
}

export interface MoveJobRequest {
  jobId: string
  /** The destination column id, which is also the job's new status key. */
  status: string
  anchorJobId?: string
  placement?: Placement
}

export interface KanbanBoardModel {
  columns: KanbanColumnView[]
  isSearchActive: boolean
  activeStaffIds: string[]
  toggleStaffFilter: (staffId: string) => void
  moveJob: (request: MoveJobRequest) => void
  /**
   * A ref, not state: pragmatic's draggable() is registered in an effect, and
   * a state change here would tear that registration down and rebuild it
   * mid-drag, aborting the drag the flag exists to guard.
   */
  movePendingRef: React.RefObject<boolean>
}

/**
 * v1 jobMatchesStaffFilters (useOptimizedKanban.ts:214): a job matches when
 * any selected staff member is assigned to it OR created it. v1's leading
 * "archived jobs always show" branch is dropped, not lost: the office board
 * renders no archived column, so the branch is unreachable here — and it
 * tested the display label `status === 'Archived'`, which is presentation.
 */
function jobMatchesStaffFilters(job: KanbanJobOut, activeStaffIds: string[]): boolean {
  if (activeStaffIds.length === 0) return true
  if (job.people.some((person) => activeStaffIds.includes(person.id))) return true
  return job.created_by_id !== null && activeStaffIds.includes(job.created_by_id)
}

export function useKanbanBoard(searchQuery: string): KanbanBoardModel {
  const queryClient = useQueryClient()
  const [activeStaffIds, setActiveStaffIds] = useState<string[]>([])
  const movePendingRef = useRef(false)

  const statusValues = useQuery(jobJobsStatusValuesRetrieveOptions())
  const columnQueries = useQueries({
    queries: OFFICE_COLUMN_IDS.map((columnId) =>
      jobJobsFetchByColumnRetrieveOptions(columnFetchOptions(columnId)),
    ),
  })

  const searchTerm = searchQuery.trim()
  const isSearchActive = searchTerm.length > 0
  const search = useQuery({
    ...jobJobsAdvancedSearchRetrieveOptions({ query: { q: searchTerm } }),
    enabled: isSearchActive,
  })

  // useQueries mirrors the array it was handed, so a missing entry is a bug
  // in this file rather than anything a user can cause — fail here instead of
  // rendering a column with no query behind it.
  const columnStates = columnQueries.map((query, index) => {
    const columnId = OFFICE_COLUMN_IDS[index]
    if (columnId === undefined) {
      throw new Error(
        `Column query ${index} has no column id (${OFFICE_COLUMN_IDS.length} columns)`,
      )
    }
    return { columnId, query }
  })

  // One toast per distinct failure. The E2E console guard fails a spec on any
  // console.error, so a failed board load has to surface as a toast or not at
  // all — and the board mounts under every spec's login.
  const loadErrors: Array<{ label: string; error: Error | null }> = columnStates.map(
    ({ columnId, query }) => ({ label: `the ${columnId} column`, error: query.error }),
  )
  loadErrors.push({ label: 'the board columns', error: statusValues.error })
  loadErrors.push({ label: 'search results', error: search.error })
  const latestLoadErrors = useRef(loadErrors)
  latestLoadErrors.current = loadErrors
  const loadErrorSignature = loadErrors
    .map((entry) => `${entry.label}:${entry.error?.message ?? ''}`)
    .join('|')
  useEffect(() => {
    for (const entry of latestLoadErrors.current) {
      if (entry.error) {
        toast.error(apiErrorMessage(entry.error, `Failed to load ${entry.label}`))
      }
    }
  }, [loadErrorSignature])

  const searchGroups = useMemo(() => {
    if (!isSearchActive) return null
    const groups = new Map<string, KanbanJobOut[]>()
    for (const job of search.data?.jobs ?? []) {
      const existing = groups.get(job.status_key)
      if (existing) {
        existing.push(job)
      } else {
        groups.set(job.status_key, [job])
      }
    }
    return groups
  }, [isSearchActive, search.data])

  const columns: KanbanColumnView[] = columnStates.map(({ columnId, query }) => {
    const columnJobs: KanbanJobOut[] = query.data?.jobs ?? []
    const base = searchGroups ? (searchGroups.get(columnId) ?? []) : columnJobs
    const jobs = activeStaffIds.length
      ? base.filter((job) => jobMatchesStaffFilters(job, activeStaffIds))
      : base

    // Ported verbatim from v1 KanbanColumn.vue:199-209. While searching, Y is
    // the column's own loaded count; while truncated, Y is the API total.
    const loadedCount = columnJobs.length
    const total = query.data?.total ?? null
    let countDisplay: string
    if (isSearchActive && jobs.length !== loadedCount) {
      countDisplay = `${jobs.length} of ${loadedCount.toLocaleString()}`
    } else if (query.data?.has_more === true && total !== null) {
      countDisplay = `${jobs.length} of ${total.toLocaleString()}`
    } else {
      countDisplay = String(jobs.length)
    }

    return {
      id: columnId,
      label: statusValues.data?.statuses[columnId] ?? fallbackColumnLabel(columnId),
      tooltip: statusValues.data?.tooltips[columnId] ?? `Status: ${fallbackColumnLabel(columnId)}`,
      jobs,
      countDisplay,
      isLoading: query.isPending || (isSearchActive && search.isPending),
    }
  })

  const toggleStaffFilter = useCallback((staffId: string) => {
    setActiveStaffIds((current) =>
      current.includes(staffId)
        ? current.filter((candidate) => candidate !== staffId)
        : [...current, staffId],
    )
  }, [])

  const reorder = useMutation(jobJobsReorderCreateMutation())

  const moveJob = useCallback(
    (request: MoveJobRequest) => {
      // One move at a time: two overlapping reorders anchor against each
      // other's un-persisted positions, and the loser silently wins.
      if (movePendingRef.current) return
      movePendingRef.current = true

      const job = findColumnJob(queryClient, request.jobId)
      const affected =
        job && job.status_key !== request.status
          ? [job.status_key, request.status]
          : [request.status]
      const snapshot = snapshotColumns(queryClient, affected)

      if (job) {
        // `status` (the display label) is left stale on purpose: nothing
        // renders it, and inventing a label here would be a second source of
        // truth for the one the server sends back.
        applyJobUpsert(
          queryClient,
          { ...job, status_key: request.status },
          request.anchorJobId && request.placement
            ? { anchorJobId: request.anchorJobId, placement: request.placement }
            : undefined,
        )
      }

      reorder.mutate(
        {
          path: { job_id: request.jobId },
          body: {
            anchor_job_id: request.anchorJobId ?? null,
            placement: request.placement ?? null,
            status: request.status,
          },
        },
        {
          onError: (error) => {
            toast.error(apiErrorMessage(error, 'Failed to move the job'))
            restoreSnapshot(queryClient, snapshot)
            for (const columnId of affected) {
              void queryClient.invalidateQueries({ queryKey: columnQueryKey(columnId) })
            }
          },
          onSettled: () => {
            movePendingRef.current = false
          },
        },
      )
    },
    [queryClient, reorder],
  )

  // SEAM: kanban-changes reconciliation (useKanbanReconciliation) hooks in
  // here next slice — it polls getKanbanChanges and replays the deltas
  // through boardCache's applyJobUpsert/removeJob, which is what confirms
  // server truth for the reorders deliberately not invalidated above.

  return {
    columns,
    isSearchActive,
    activeStaffIds,
    toggleStaffFilter,
    moveJob,
    movePendingRef,
  }
}
