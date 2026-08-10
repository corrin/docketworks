/**
 * Keeping the board fresh across users, incrementally.
 *
 * The board's six column queries deliberately do not refetch after a move
 * (useKanbanBoard's header says why), so server truth — including everyone
 * else's edits — has to arrive some other way. That way is this loop: a tiny
 * data-versions poll says *whether* anything changed, and only when it did do
 * we fetch the changed cards and replay them through boardCache. Refetching
 * six 200-row columns every 30s is the thing this exists to not do.
 *
 * The trigger and the handler are separate on purpose. `reconcile()` is the
 * whole "version moved -> fetch diff -> apply" pass and takes no arguments;
 * the 30s interval is merely its first caller. The push channel (SSE) becomes
 * a second caller that runs the same pass sooner, at which point the interval
 * degrades to a fallback for a dropped stream rather than being replaced.
 */
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { apiErrorMessage, getKanbanChangesOptions, isApiErrorStatus } from '@/api'
import type { DataVersions, KanbanChangesResponse, KanbanColumnJobOut } from '@/api'
import { dataVersionsQueryOptions } from '@/features/shell'

import {
  applyJobUpsert,
  invalidateAllColumns,
  isBeyondColumnWindow,
  removeJob,
  searchQueryKey,
} from './boardCache'
import { OFFICE_COLUMN_IDS } from './columns'

/**
 * How often the fallback trigger asks whether anything changed. Matched to
 * v1's kanban poll so the server sees no new load profile at cutover; the
 * response is four short strings, and TanStack's refetchInterval only fires
 * while the tab is focused (refetchIntervalInBackground defaults to false in
 * @tanstack/query-core 5.101 — queryObserver's interval callback fires
 * executeFetch only when that option is set or focusManager.isFocused()).
 */
export const RECONCILE_INTERVAL_MS = 30_000

/** The opaque server versions this loop tracks. Never parsed, never synthesised. */
interface KanbanCursor {
  kanban: string
  kanbanRelated: string
}

export interface KanbanReconciliationOptions {
  /**
   * True while a pointer drag is in flight. A ref, not state: the pause is
   * read at tick time and a re-render here would tear down the pragmatic
   * registrations mid-gesture (useKanbanDrag's header).
   */
  isDraggingRef: React.RefObject<boolean>
  /** True while a move POST is in flight — moveJob and updateStatus share it. */
  movePendingRef: React.RefObject<boolean>
  /** The trimmed search term; '' when no search is active. */
  searchTerm: string
}

export interface KanbanReconciliation {
  /**
   * Run one pass now. Safe to call at any time and from any trigger: it
   * no-ops unless the cached kanban version has moved past the cursor, and it
   * defers entirely while a drag or a move is in flight.
   */
  reconcile: () => Promise<void>
}

/**
 * Replay one changes response into the column caches.
 *
 * Exported for its own tests and for the push channel, which will hand it a
 * payload from the stream instead of from a fetch. Every write goes through
 * boardCache — this module holds no cache-writing code of its own.
 */
export function applyKanbanChanges(
  queryClient: QueryClient,
  changes: KanbanChangesResponse,
  searchTerm: string,
): void {
  if (changes.full_refresh_required) {
    // The dataset's topology moved (a job was created or deleted), so the
    // server could not express the delta and sent no cards to apply.
    invalidateAllColumns(queryClient)
    return
  }

  for (const jobId of changes.removed_job_ids) {
    removeJob(queryClient, jobId)
  }

  for (const job of changes.jobs) {
    applyChangedJob(queryClient, job)
  }

  // Search results render straight from the search query and no cache writer
  // touches them, so a card whose status changed remotely keeps rendering
  // under its old heading until this refetches (moveJob and updateStatus
  // invalidate it after their own writes for the same reason).
  const changed = changes.jobs.length > 0 || changes.removed_job_ids.length > 0
  if (searchTerm.length > 0 && changed) {
    void queryClient.invalidateQueries({ queryKey: searchQueryKey(searchTerm) })
  }
}

const VISIBLE_COLUMN_IDS: readonly string[] = OFFICE_COLUMN_IDS

function applyChangedJob(queryClient: QueryClient, job: KanbanColumnJobOut): void {
  if (!VISIBLE_COLUMN_IDS.includes(job.status_key)) {
    // Archived, special, rejected — the office board renders no column for
    // these, so the card's new home is "nowhere on screen". Upserting would
    // drop it from its old column and insert it into no column, which is the
    // same outcome by a longer route; removeJob says what is happening.
    removeJob(queryClient, job.id)
    return
  }
  if (isBeyondColumnWindow(queryClient, job.status_key, job)) {
    // The card now lives past the loaded window of a truncated column. It
    // must still leave whatever column it was in, or the board would show it
    // twice once the truncated column is scrolled or refetched.
    removeJob(queryClient, job.id)
    return
  }
  applyJobUpsert(queryClient, job, { kind: 'priority' })
}

export function useKanbanReconciliation({
  isDraggingRef,
  movePendingRef,
  searchTerm,
}: KanbanReconciliationOptions): KanbanReconciliation {
  const queryClient = useQueryClient()

  // The shell ensureQueryData'd this before any authed page rendered, so the
  // observer starts from cache (staleTime 5min) and mounting the board fires
  // no request; the interval is the only thing that refetches it.
  const versions = useQuery({
    ...dataVersionsQueryOptions(),
    refetchInterval: RECONCILE_INTERVAL_MS,
  })

  const cursorRef = useRef<KanbanCursor | null>(null)
  const failingRef = useRef(false)
  const searchTermRef = useRef(searchTerm)
  searchTermRef.current = searchTerm

  const reconcile = useCallback(async (): Promise<void> => {
    const polled = queryClient.getQueryData<DataVersions>(dataVersionsQueryOptions().queryKey)
    if (polled === undefined) return

    if (cursorRef.current === null) {
      // First pass: establish where "since" starts. Deliberately ahead of the
      // pause check — seeding applies no diff, and skipping it would silently
      // widen the window of changes the first real tick has to catch up on.
      cursorRef.current = { kanban: polled.kanban, kanbanRelated: polled.kanban_related }
      return
    }

    // Pause and defer. The cursor stays put, so the next tick asks the same
    // question and the server answers with a superset — the feed is
    // cursor-idempotent, which is why no replay buffer is needed here.
    if (isDraggingRef.current || movePendingRef.current) return

    const cursor = cursorRef.current
    const kanbanMoved = polled.kanban !== cursor.kanban
    const relatedMoved = polled.kanban_related !== cursor.kanbanRelated
    if (!kanbanMoved && !relatedMoved) return

    if (kanbanMoved) {
      let changes: KanbanChangesResponse
      try {
        changes = await queryClient.fetchQuery({
          ...getKanbanChangesOptions({ query: { after: cursor.kanban } }),
          // One shot, kept out of the cache: every cursor is a distinct query
          // key, so a retained entry per tick is an unbounded leak, and the
          // retry for a failed pass is the next tick rather than an inner one.
          staleTime: 0,
          gcTime: 0,
          retry: false,
        })
      } catch (error) {
        if (isApiErrorStatus(error, 400)) {
          // The server refused the cursor (apps/job/api.py get_kanban_changes
          // 400s on an undecodable version). It cannot tell us what changed,
          // so the columns have to be re-read — and the cursor is reseeded
          // from `polled`, which IS a fresh data-versions read: this pass was
          // triggered by it, so fetching data-versions again would only ask
          // the same question a second time.
          invalidateAllColumns(queryClient)
          failingRef.current = false
          cursorRef.current = { kanban: polled.kanban, kanbanRelated: polled.kanban_related }
          return
        }
        // Cursor unchanged: whatever moved is still unseen, and the next tick
        // asks from the same point. One toast per failure streak, cleared on
        // the first success — a toast every 30s on a flaky connection is
        // worse than silence, but a permanently dead poll must not be
        // invisible. Never console.error: the E2E console guard fails any
        // spec that logs one, and the board mounts under every spec.
        if (!failingRef.current) {
          failingRef.current = true
          toast.error(apiErrorMessage(error, 'Failed to refresh the board'))
        }
        return
      }
      failingRef.current = false
      applyKanbanChanges(queryClient, changes, searchTermRef.current)
    }

    if (relatedMoved) {
      // A staff rename or a company rename changes what every card displays
      // without touching a single Job row, so there is no delta to apply —
      // only the columns can be re-read. Last, because applyJobUpsert cancels
      // in-flight column fetches and would abort these refetches.
      invalidateAllColumns(queryClient)
    }

    cursorRef.current = { kanban: polled.kanban, kanbanRelated: polled.kanban_related }
  }, [queryClient, isDraggingRef, movePendingRef])

  // One pass per completed poll. dataUpdatedAt (not the version string) is the
  // dependency because a tick has to run even when the poll returns the value
  // we already had: a pass deferred by a drag gets its retry from the next
  // poll, and no version has to move for that retry to be owed.
  const reconcileRef = useRef(reconcile)
  reconcileRef.current = reconcile
  useEffect(() => {
    void reconcileRef.current()
  }, [versions.dataUpdatedAt])

  return { reconcile }
}
