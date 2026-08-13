/**
 * Keeping the board fresh across users, incrementally.
 *
 * The board's six column queries deliberately do not refetch after a move
 * (useKanbanBoard's header says why), so server truth — including everyone
 * else's edits — has to arrive some other way. That way is this loop: a tiny
 * data-versions document says *whether* anything changed, and only when it did
 * do we fetch the changed cards and replay them through boardCache. Refetching
 * six 200-row columns on every change is the thing this exists to not do.
 *
 * The trigger and the handler are separate on purpose. `reconcile()` is the
 * whole "version moved -> fetch diff -> apply" pass and takes no arguments,
 * and three things call it: the push channel (an SSE stream of the very
 * documents the poll returns), a drag/move release (KanbanBoard's
 * reconcileRef), and the poll. The push channel is the primary trigger, and
 * the poll is the fallback for a dropped stream: it runs only while the
 * stream is down, and stops the moment one connects.
 *
 * Exactly one of the two owns the trigger at any time, because both feed the
 * same data-versions query. While the stream is connected the query's own
 * observer stops firing passes — every write to it came from the stream
 * handler, which runs its own debounced pass, and a second pass from the
 * observer would race a duplicate changes fetch against it.
 *
 * Rejected alternative (ADR 0032): a generic incremental-sync library
 * (Replicache, ElectricSQL, PowerSync, Triplit) rather than this hand-rolled
 * poll-then-diff loop. Those solve a superset of this problem — offline
 * writes, generic conflict resolution, arbitrary schema sync over a bespoke
 * protocol — at the cost of a new server-side sync endpoint, a new client
 * runtime, and a new protocol replacing the two plain REST endpoints this
 * already has (`data-versions`, `kanban-changes`). Nothing here needs the
 * offline half, and the library would be more glue to adopt than the ~280
 * lines it would remove (ADR 0032's "demands more glue than it removes"
 * clause). If a future slice needs offline support or multi-entity sync
 * beyond kanban, re-evaluate against this file rather than assuming the
 * conclusion still holds.
 */
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  getKanbanChangesOptions,
  isApiErrorStatus,
  runDataVersionsStream,
} from '@/api'
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
 * How often the fallback trigger asks whether anything changed, while the push
 * channel is down. Matched to v1's kanban poll so the server sees no new load
 * profile at cutover; the response is four short strings, and TanStack's
 * refetchInterval only fires while the tab is focused
 * (refetchIntervalInBackground defaults to false in @tanstack/query-core
 * 5.101 — queryObserver's interval callback fires executeFetch only when that
 * option is set or focusManager.isFocused()).
 */
export const RECONCILE_INTERVAL_MS = 30_000

/**
 * Trailing debounce on the push-driven pass — a burst absorber, not a delay
 * budget. One user's drag emits several version pushes in under a second, and
 * each pass costs a changes fetch whose answer is a superset of the last, so
 * the burst is worth one question rather than five.
 */
const STREAM_RECONCILE_DEBOUNCE_MS = 300

/**
 * Said once per outage, not once per retry. The sentence names the fallback
 * because that is the part the user can act on: the board is still current
 * within 30s, it just stopped being instant.
 */
const STREAM_DISCONNECTED_MESSAGE = 'Live updates disconnected — falling back to periodic refresh'

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
    // server could not express the delta and sent no cards to apply. The
    // search query is invalidated on this path too, unconditionally: it is
    // not fed by any cache writer, and "a job was created or deleted" is
    // exactly the change a searching user's list must not miss.
    invalidateAllColumns(queryClient)
    invalidateSearch(queryClient, searchTerm)
    return
  }

  for (const jobId of changes.removed_job_ids) {
    removeJob(queryClient, jobId)
  }

  for (const job of changes.jobs) {
    applyChangedJob(queryClient, job)
  }

  if (changes.jobs.length > 0 || changes.removed_job_ids.length > 0) {
    invalidateSearch(queryClient, searchTerm)
  }
}

/**
 * Search results render straight from the search query and no cache writer
 * touches them, so a card whose status changed remotely keeps rendering under
 * its old heading until this refetches (moveJob and updateStatus invalidate it
 * after their own writes for the same reason). A no-op when no search is
 * active, so callers do not each repeat that test.
 */
function invalidateSearch(queryClient: QueryClient, searchTerm: string): void {
  if (searchTerm.length === 0) return
  void queryClient.invalidateQueries({ queryKey: searchQueryKey(searchTerm) })
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

  // State because refetchInterval is read at render time, so flipping this is
  // how the fallback poll is switched off and back on; a ref alongside it
  // because the stream callbacks decide who owns the reconcile trigger and run
  // before React has committed the state update. Written only together, by
  // setStreamHealth.
  const [streamHealthy, setStreamHealthy] = useState(false)
  const streamHealthyRef = useRef(false)
  const setStreamHealth = useCallback((healthy: boolean): void => {
    streamHealthyRef.current = healthy
    setStreamHealthy(healthy)
  }, [])

  // The shell ensureQueryData'd this before any authed page rendered, so the
  // observer starts from cache (staleTime 5min) and mounting the board fires
  // no request.
  const versions = useQuery({
    ...dataVersionsQueryOptions(),
    refetchInterval: streamHealthy ? false : RECONCILE_INTERVAL_MS,
  })

  const cursorRef = useRef<KanbanCursor | null>(null)
  // Three streaks, not one: the changes fetch, the versions poll and the push
  // channel fail independently, and a shared flag would let a healthy poll
  // clear the flag every 30s and re-arm the toast for a permanently broken
  // changes endpoint — the toast storm the single-toast rule exists to prevent.
  const changesFailingRef = useRef(false)
  const versionsFailingRef = useRef(false)
  const streamFailingRef = useRef(false)
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
          invalidateSearch(queryClient, searchTermRef.current)
          changesFailingRef.current = false
          cursorRef.current = { kanban: polled.kanban, kanbanRelated: polled.kanban_related }
          return
        }
        // Cursor unchanged: whatever moved is still unseen, and the next tick
        // asks from the same point.
        reportStreak(changesFailingRef, apiErrorMessage(error, 'Failed to refresh the board'))
        return
      }
      changesFailingRef.current = false

      // Re-tested AFTER the await, not only before it: the user can start a
      // drag or a move while this fetch is open, and the response was computed
      // before that move existed. Applying it would replay pre-move server
      // state over the optimistic write and visibly revert the card — v1's
      // vanishing/reverting card, arriving by a new route. The cursor does not
      // advance, so the next tick asks from the same point and the feed
      // answers with a superset that includes the move.
      if (isDraggingRef.current || movePendingRef.current) return

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
  // poll, and no version has to move for that retry to be owed. errorUpdatedAt
  // is a dependency for the mirror-image reason: a failing poll never moves
  // dataUpdatedAt, so without it a dead versions endpoint would freeze the
  // board with no tick, no toast and nothing in the console to find it by.
  const reconcileRef = useRef(reconcile)
  reconcileRef.current = reconcile
  const versionsError = versions.error
  useEffect(() => {
    if (versionsError) {
      reportStreak(
        versionsFailingRef,
        apiErrorMessage(versionsError, 'Failed to check the board for changes'),
      )
      return
    }
    versionsFailingRef.current = false
    // The stream owns the trigger while it is connected (see the header): this
    // effect fires on every write to the query, and the stream handler's own
    // debounced pass is already covering the ones it made.
    if (streamHealthyRef.current) return
    void reconcileRef.current()
  }, [versions.dataUpdatedAt, versions.errorUpdatedAt, versionsError])

  // The push channel: opened once per mount, closed on unmount, and the source
  // of every pass while it is up.
  useEffect(() => {
    const controller = new AbortController()
    let burst: ReturnType<typeof setTimeout> | undefined

    void runDataVersionsStream({
      signal: controller.signal,
      onDataVersions: (pushed) => {
        // Into the cache first: reconcile() diffs the CACHED document against
        // its cursor and takes no argument, so a pass run before this write
        // would find nothing moved and do nothing.
        queryClient.setQueryData(dataVersionsQueryOptions().queryKey, pushed)
        clearTimeout(burst)
        burst = setTimeout(() => void reconcileRef.current(), STREAM_RECONCILE_DEBOUNCE_MS)
      },
      onStreamOpen: () => {
        // Ownership moves before the read below, not after it: that read
        // writes the same query, and the observer effect above must already be
        // deferring to this pass rather than racing a second one against it.
        setStreamHealth(true)
        streamFailingRef.current = false
        void catchUpAfterConnect(queryClient, reconcileRef)
      },
      onDisconnect: () => {
        setStreamHealth(false)
        reportStreak(streamFailingRef, STREAM_DISCONNECTED_MESSAGE)
      },
    })

    return () => {
      controller.abort()
      clearTimeout(burst)
    }
  }, [queryClient, setStreamHealth])

  return { reconcile }
}

/**
 * Re-read the versions and run a pass, because a newly connected tab does not
 * know what it missed.
 *
 * The server emits no event ids (django-eventstream is configured with no
 * storage backend), so there is no Last-Event-ID resume and the gap is the
 * client's to close. staleTime 0 overrides the shared 5-minute freshness of
 * dataVersionsQueryOptions: fetchQuery honours staleTime, and returning the
 * cached copy is exactly the answer that cannot close a gap. Undebounced —
 * this runs once per connection, not once per event.
 */
async function catchUpAfterConnect(
  queryClient: QueryClient,
  reconcileRef: React.RefObject<() => Promise<void>>,
): Promise<void> {
  try {
    await queryClient.fetchQuery({ ...dataVersionsQueryOptions(), staleTime: 0 })
  } catch {
    // The failure is already recorded on the shared versions query, whose
    // error path above raises the poll's own streak toast; reporting it again
    // here would double it, and rethrowing inside this fire-and-forget call
    // would only surface as an unhandled rejection.
    return
  }
  await reconcileRef.current()
}

/**
 * One toast per failure streak, silent until the streak breaks.
 *
 * A toast every 30s on a flaky connection is worse than silence, but a
 * permanently dead loop must not be invisible — and console.error is not an
 * option at all: the E2E console guard fails any spec that logs one, and the
 * board mounts under every spec. Recovery clears the flag at the call site, so
 * a second outage is reported again.
 */
function reportStreak(streakRef: React.RefObject<boolean>, message: string): void {
  if (streakRef.current) return
  streakRef.current = true
  toast.error(message)
}
