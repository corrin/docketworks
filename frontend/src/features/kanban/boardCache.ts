/**
 * The only writers of the kanban column query caches.
 *
 * The board keeps no store: the six per-column TanStack queries ARE the
 * model, and render order is cache order is the server's `-priority` order.
 * Every optimistic move therefore has to edit those caches directly, and it
 * has to do it in exactly one place — v1 had the same edit open-coded in the
 * page, the composable and the drag handler, which is how a moved card could
 * end up rendered in two columns at once.
 */
import type { QueryClient } from '@tanstack/react-query'

import { jobJobsAdvancedSearchRetrieveQueryKey, jobJobsFetchByColumnRetrieveQueryKey } from '@/api'
import type { FetchJobsByColumnResponse, KanbanColumnJobOut } from '@/api'

import { OFFICE_COLUMN_IDS } from './columns'

/**
 * Per-column fetch ceiling. Not "all": the E2E wire guard fails any response
 * over 100KB, and an unbounded column is exactly the missing-limit bug that
 * guard exists to catch.
 */
export const COLUMN_MAX_JOBS = 200

/** The one place a column's request options are built — key and query agree by construction. */
export function columnFetchOptions(columnId: string) {
  return { path: { column_id: columnId }, query: { max_jobs: COLUMN_MAX_JOBS } }
}

export function columnQueryKey(columnId: string) {
  return jobJobsFetchByColumnRetrieveQueryKey(columnFetchOptions(columnId))
}

/**
 * The search query's key. Search results are rendered straight from that
 * query and no cache writer here touches them, so an optimistic edit made
 * while a search is active is invisible until the search is refetched — the
 * two hooks invalidate this after a write for exactly that reason.
 */
export function searchQueryKey(searchTerm: string) {
  return jobJobsAdvancedSearchRetrieveQueryKey({ query: { q: searchTerm } })
}

export type Placement = 'above' | 'below'

export interface UpsertAnchor {
  /** The visible card the moved card is placed against. */
  anchorJobId: string
  placement: Placement
}

export interface ColumnSnapshot {
  columnId: string
  data: FetchJobsByColumnResponse | undefined
}

function insertAgainstAnchor(
  jobs: KanbanColumnJobOut[],
  job: KanbanColumnJobOut,
  anchor: UpsertAnchor | undefined,
): KanbanColumnJobOut[] {
  if (!anchor) {
    // No anchor means the server will give the job top priority (an empty
    // target column, or an explicit status change), so the optimistic
    // position has to be the top too.
    return [job, ...jobs]
  }
  const anchorIndex = jobs.findIndex((candidate) => candidate.id === anchor.anchorJobId)
  if (anchorIndex === -1) {
    return [job, ...jobs]
  }
  const insertAt = anchor.placement === 'above' ? anchorIndex : anchorIndex + 1
  return [...jobs.slice(0, insertAt), job, ...jobs.slice(insertAt)]
}

/**
 * Move a card to the column its `status_key` names, at the anchor position.
 * Returns whether the card was actually inserted — false means the
 * destination column holds no cached data to insert into, and the caller owes
 * that column an invalidation once the server has the move (see moveJob).
 * Without that, removing the card from its source and inserting it nowhere
 * would make it vanish from the board entirely.
 *
 * Every column with data is cancelled first, not just the two involved. A
 * refetch that was already in flight resolves with pre-move data and
 * overwrites whatever we wrote — that is v1's vanishing-card bug, where a
 * card dropped into a new column reappeared in its old one a second later and
 * then disappeared from both on the next poll.
 */
export function applyJobUpsert(
  queryClient: QueryClient,
  job: KanbanColumnJobOut,
  anchor?: UpsertAnchor,
): boolean {
  for (const columnId of OFFICE_COLUMN_IDS) {
    // A column still on its FIRST fetch is skipped: cancelQueries reverts a
    // query to its pre-fetch state, and for an initial load that state is
    // "pending with nothing scheduled" — the column would render its loading
    // view forever, because a successful reorder deliberately invalidates
    // nothing. Only a query that already has data can have a refetch worth
    // racing anyway.
    if (queryClient.getQueryData(columnQueryKey(columnId)) === undefined) continue
    void queryClient.cancelQueries({ queryKey: columnQueryKey(columnId) })
  }

  let inserted = false
  for (const columnId of OFFICE_COLUMN_IDS) {
    queryClient.setQueryData<FetchJobsByColumnResponse>(columnQueryKey(columnId), (current) => {
      if (!current) return current
      const without = current.jobs.filter((candidate) => candidate.id !== job.id)
      if (columnId !== job.status_key) {
        // Untouched columns keep their identity so React skips re-rendering them.
        return without.length === current.jobs.length ? current : { ...current, jobs: without }
      }
      inserted = true
      return { ...current, jobs: insertAgainstAnchor(without, job, anchor) }
    })
  }
  return inserted
}

/** Drop a card from every column — the reconciliation feed's removal path. */
export function removeJob(queryClient: QueryClient, jobId: string): void {
  for (const columnId of OFFICE_COLUMN_IDS) {
    queryClient.setQueryData<FetchJobsByColumnResponse>(columnQueryKey(columnId), (current) => {
      if (!current) return current
      const without = current.jobs.filter((candidate) => candidate.id !== jobId)
      return without.length === current.jobs.length ? current : { ...current, jobs: without }
    })
  }
}

/**
 * Edit a card wherever it currently sits, without moving it. Distinct from
 * applyJobUpsert on purpose: a staff assignment changes the card's contents,
 * and re-inserting it would send it to the top of its column.
 */
export function updateJobInPlace(
  queryClient: QueryClient,
  jobId: string,
  update: (job: KanbanColumnJobOut) => KanbanColumnJobOut,
): void {
  for (const columnId of OFFICE_COLUMN_IDS) {
    queryClient.setQueryData<FetchJobsByColumnResponse>(columnQueryKey(columnId), (current) => {
      if (!current) return current
      if (!current.jobs.some((candidate) => candidate.id === jobId)) return current
      return {
        ...current,
        jobs: current.jobs.map((candidate) =>
          candidate.id === jobId ? update(candidate) : candidate,
        ),
      }
    })
  }
}

/** The cached card for a job id, or null when no loaded column holds it. */
export function findColumnJob(queryClient: QueryClient, jobId: string): KanbanColumnJobOut | null {
  for (const columnId of OFFICE_COLUMN_IDS) {
    const data = queryClient.getQueryData<FetchJobsByColumnResponse>(columnQueryKey(columnId))
    const job = data?.jobs.find((candidate) => candidate.id === jobId)
    if (job) return job
  }
  return null
}

export function snapshotColumns(queryClient: QueryClient, columnIds: string[]): ColumnSnapshot[] {
  return columnIds.map((columnId) => ({
    columnId,
    data: queryClient.getQueryData<FetchJobsByColumnResponse>(columnQueryKey(columnId)),
  }))
}

export function restoreSnapshot(queryClient: QueryClient, snapshot: ColumnSnapshot[]): void {
  for (const entry of snapshot) {
    queryClient.setQueryData<FetchJobsByColumnResponse>(columnQueryKey(entry.columnId), entry.data)
  }
}
