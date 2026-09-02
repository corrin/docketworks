/**
 * The only writers of the kanban column query caches.
 *
 * The board keeps no store: the per-column TanStack queries ARE the
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

/**
 * Where an upsert drops the card inside its destination column.
 *
 * `top` and `anchor` are the two optimistic shapes: the client is guessing
 * what the server is about to decide, and the guess is expressed as a
 * position relative to what the user just saw. `priority` is the opposite —
 * the server has already decided, the card carries its real `priority`, and
 * the only correct slot is the one that keeps the column in the descending
 * order the server sends. Reconciliation must never use `top`: replaying a
 * remote edit would jump an unrelated card to the head of the column.
 */
export type UpsertPosition =
  /** Top of the column — an empty destination, or an explicit status change. */
  | { kind: 'top' }
  /** Against a visible card — the drag path. */
  | { kind: 'anchor'; anchor: UpsertAnchor }
  /** At the card's own descending-priority slot — the reconciliation path. */
  | { kind: 'priority' }

export interface ColumnSnapshot {
  columnId: string
  data: FetchJobsByColumnResponse | undefined
}

function insertAt(
  jobs: KanbanColumnJobOut[],
  job: KanbanColumnJobOut,
  index: number,
): KanbanColumnJobOut[] {
  return [...jobs.slice(0, index), job, ...jobs.slice(index)]
}

function insertByPosition(
  jobs: KanbanColumnJobOut[],
  job: KanbanColumnJobOut,
  position: UpsertPosition,
): KanbanColumnJobOut[] {
  if (position.kind === 'top') return [job, ...jobs]
  if (position.kind === 'priority') {
    // Ties keep the incumbent ahead (>= rather than >): the server breaks
    // equal priorities by a secondary key this response does not carry, so
    // the least-wrong guess is not to reorder cards we were not told about.
    const slot = jobs.findIndex((candidate) => candidate.priority < job.priority)
    return slot === -1 ? [...jobs, job] : insertAt(jobs, job, slot)
  }
  const anchorIndex = jobs.findIndex((candidate) => candidate.id === position.anchor.anchorJobId)
  if (anchorIndex === -1) {
    // The anchor is gone (filtered out, or removed by a reconciliation tick
    // between the drag starting and the drop landing), so the position the
    // user aimed at no longer exists; the server's answer arrives on the next
    // reconciliation tick and moves the card to its real slot.
    return [job, ...jobs]
  }
  return insertAt(jobs, job, position.anchor.placement === 'above' ? anchorIndex : anchorIndex + 1)
}

/**
 * True when the card belongs past the end of a column's loaded window.
 *
 * A column is capped at COLUMN_MAX_JOBS, and `has_more` says the server had
 * more to send. A remote change to a card whose priority sorts below the last
 * card we hold therefore describes a card that is not — and must not become —
 * visible: appending it would render row 201 above the rows 201..N that the
 * column never fetched, and the count display would disagree with the list.
 * An untruncated column has no window to fall outside of.
 */
export function isBeyondColumnWindow(
  queryClient: QueryClient,
  columnId: string,
  job: KanbanColumnJobOut,
): boolean {
  const data = queryClient.getQueryData<FetchJobsByColumnResponse>(columnQueryKey(columnId))
  if (!data || data.has_more !== true) return false
  const others = data.jobs.filter((candidate) => candidate.id !== job.id)
  const last = others[others.length - 1]
  if (last === undefined) return false
  return job.priority < last.priority
}

/**
 * Mark every column stale so TanStack refetches the ones on screen.
 *
 * The whole-column hammer, deliberately reachable from only three places
 * (kanban_related moved, full_refresh_required, a rejected cursor): the board
 * exists to avoid exactly this refetch, so a fourth caller is a design bug
 * rather than a convenience.
 */
export function invalidateAllColumns(queryClient: QueryClient): void {
  for (const columnId of OFFICE_COLUMN_IDS) {
    const key = columnQueryKey(columnId)
    const state = queryClient.getQueryState(key)
    if (state?.data === undefined && state?.fetchStatus === 'fetching') {
      // A column still on its FIRST fetch does not restart on invalidation —
      // query-core's Query.fetch only honours cancelRefetch once state.data
      // exists, so the invalidation rides the in-flight request, and that
      // request may have been issued before the change we are invalidating
      // for. Chaining a refetch onto it (by which time data exists, so the
      // dedup no longer applies) is what makes the column end up post-change.
      // This is the same dedup that makes a reorder's own invalidation
      // unreliable, which is why the board leans on the diff feed instead.
      void queryClient
        .invalidateQueries({ queryKey: key })
        .then(() => queryClient.refetchQueries({ queryKey: key }))
      continue
    }
    void queryClient.invalidateQueries({ queryKey: key })
  }
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
  position: UpsertPosition = { kind: 'top' },
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
      return { ...current, jobs: insertByPosition(without, job, position) }
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
