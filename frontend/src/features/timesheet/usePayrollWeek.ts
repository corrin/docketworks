/**
 * Pay-run state and the posting run for one payroll week.
 *
 * Opus: Server state (which pay runs exist, which week may be posted) stays in the
 * Query cache. The only local state is the progress of a run in flight, which
 * is not server state — it is a conversation with a task, and it ends.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  runPayrollRunsStream,
  timesheetsPayrollPayRunsCreateCreateMutation,
  timesheetsPayrollPayRunsRefreshCreateMutation,
  timesheetsPayrollPayRunsRetrieveOptions,
  timesheetsPayrollPayRunsRetrieveQueryKey,
  timesheetsPayrollPostStaffWeekCreateMutation,
  timesheetsPayrollWeekStatusRetrieveOptions,
  timesheetsPayrollWeekStatusRetrieveQueryKey,
  timesheetsWeeklyRetrieveQueryKey,
  timesheetsPayrollRunsRetrieveOptions,
  timesheetsPayrollRunsRetrieveQueryKey,
  type PayrollPostRunOut,
  type StaffWeekPostResultOut,
  type PayrollRunsOut,
  type PayRunListItemOut,
  type StaffWeekPostingOut,
} from '@/api'

/** How the selected week stands with payroll, in the words the page shows. */
export type PayRunState = 'draft' | 'posted' | 'missing'

/** How often to re-read a live run while the stream is the primary signal. */
const LIVE_RUN_POLL_MS = 10_000

/** What to do when the run's outcome is unknown — never "try posting again". */
const UNKNOWN_OUTCOME_ADVICE =
  ' It may still be running in Xero — use "Check against Xero" before posting again.'

export interface PayrollProgress {
  current: number
  total: number
  staffName: string | null
}

export interface UsePayrollWeekResult {
  payRun: PayRunListItemOut | undefined
  payRunState: PayRunState
  /**
   * The one week the server says may be posted next.
   *
   * Opus: `null` is the server's own answer — it has no postable week — and is
   * distinct from not having asked yet, which is `isLoading`. Collapsing the
   * two let an unresolved query read as "every week is postable".
   */
  postableWeekStart: string | null
  isLoading: boolean
  loadFailed: boolean
  createPayRun: () => void
  isCreating: boolean
  refreshPayRuns: () => void
  isRefreshing: boolean
  postWeek: (staffIds: string[]) => void
  isPosting: boolean
  progress: PayrollProgress | null
  results: StaffWeekPostResultOut[]
  /** Set once a post has run this session, so the button can say "Re-post". */
  hasPosted: boolean
  /**
   * What Xero holds for the week, per staff member, beside what we recorded.
   *
   * Opus: Undefined until asked for, and on failure. Deliberately NOT merged into the
   * weekly payload: this read calls Xero, and folding it in would blank the
   * grid whenever Xero is unreachable (ADR 0007).
   */
  postingStatus: StaffWeekPostingOut[] | undefined
  postingStatusFailed: boolean
  isCheckingXero: boolean
  /** Ask Xero what it holds for this week. Costs one API call per staff member. */
  checkXero: () => void
}

/** Whether a pushed document is newer than the one already held.
 *
 * Opus: Module scope, not inside the hook: it closes over nothing, and a
 * function redefined per render is a new identity in every dependency array
 * that names it.
 */
function isNewer(pushed: PayrollRunsOut, held: PayrollRunsOut | undefined): boolean {
  if (held?.post === undefined || held.post === null) return true
  if (pushed.post === undefined || pushed.post === null) return false
  return pushed.post.updated_at >= held.post.updated_at
}

export function usePayrollWeek(weekStart: string): UsePayrollWeekResult {
  const queryClient = useQueryClient()
  const payRunsQuery = useQuery(timesheetsPayrollPayRunsRetrieveOptions())
  // Opus: Never on mount. Xero has no bulk leave endpoint, so this asks
  // get_employee_leaves once per staff member, and the client paces every Xero
  // call at one in flight with a 1s minimum gap — a full staff list is most of
  // a minute of Xero's quota. Opening the weekly grid must not spend that; the
  // operator asks for it, and a completed post asks for them.
  const statusQuery = useQuery({
    ...timesheetsPayrollWeekStatusRetrieveOptions({ query: { week_start_date: weekStart } }),
    enabled: false,
    staleTime: Infinity,
    retry: false,
  })
  // Opus: The run document, not local progress state. Every push carries the whole
  // of it, so reconnecting cannot duplicate results and a reload cannot lose
  // them — the two failure modes the replaced code had to remember to avoid.
  const runsQuery = useQuery({
    ...timesheetsPayrollRunsRetrieveOptions(),
    // Opus: The stream is primary; this poll is the catch-up on connect and the
    // fallback while a run is live. It is off otherwise, because a payroll run
    // is a conversation with a task, and it ends.
    refetchInterval: (query) =>
      query.state.data?.post?.status === 'running' ? LIVE_RUN_POLL_MS : false,
  })

  // Opus: A document for another week is not this week's business. The route
  // survives search-parameter navigation, so week B used to show week A's
  // per-staff results and its "Re-post to Xero" label while A's stream kept
  // writing into the display. Selecting by week makes that unrepresentable
  // rather than something a cleanup effect has to undo.
  const run: PayrollPostRunOut | null =
    runsQuery.data?.post?.week_start_date === weekStart ? runsQuery.data.post : null
  const isPosting = run?.status === 'running'
  const results = useMemo(() => run?.results ?? [], [run])
  const hasPosted = run !== null && run.status !== 'queued'
  const progress: PayrollProgress | null = isPosting
    ? { current: run.completed, total: run.total, staffName: run.current_staff_name }
    : null

  // Opus: One connection while the panel is mounted, writing each pushed document
  // into the query cache. `updated_at` is the guard: a catch-up read can still be
  // in flight when a terminal push lands, and the older answer would otherwise
  // overwrite a finished run with a running one — a panel spinning forever on a
  // run that is done.
  useEffect(() => {
    const controller = new AbortController()
    void runPayrollRunsStream({
      signal: controller.signal,
      onRuns: (pushed) => {
        queryClient.setQueryData<PayrollRunsOut>(timesheetsPayrollRunsRetrieveQueryKey(), (held) =>
          isNewer(pushed, held) ? pushed : held,
        )
      },
      // Opus: The tab is connected and owes itself whatever happened while it was
      // not. Storage-free pub/sub drops a publication rather than queueing it,
      // so this is what closes that gap.
      onStreamOpen: () => {
        void queryClient.invalidateQueries({
          queryKey: timesheetsPayrollRunsRetrieveQueryKey(),
        })
      },
    })
    // Opus: Aborting closes the stream, never the server task: the task owns the
    // posting, and abandoning the view of it is exactly what running it
    // server-side is for.
    return () => controller.abort()
  }, [queryClient])

  // Opus: Announce a run's outcome once, when it turns terminal. Derived from the
  // document rather than fired from a stream callback, so a reconnect that
  // re-delivers the terminal state cannot toast twice.
  const announced = useRef<string | null>(null)
  useEffect(() => {
    if (run === null || run.status === 'running' || run.status === 'queued') return
    if (announced.current === run.run_id) return
    announced.current = run.run_id
    reportOutcome(run)
  })

  const payRun = payRunsQuery.data?.pay_runs.find(
    (candidate) => candidate.period_start_date === weekStart,
  )
  const payRunState: PayRunState =
    payRun === undefined ? 'missing' : payRun.pay_run_status === 'Posted' ? 'posted' : 'draft'

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: timesheetsPayrollPayRunsRetrieveQueryKey() })
    void queryClient.invalidateQueries({
      queryKey: timesheetsWeeklyRetrieveQueryKey({ query: { start_date: weekStart } }),
    })
    // Opus: Invalidate rather than refetch: a disabled query stays disabled, so this
    // only marks a previously fetched answer stale. Re-reading Xero is
    // checkXero's job, and reportOutcome calls it after a post.
    void queryClient.invalidateQueries({
      queryKey: timesheetsPayrollWeekStatusRetrieveQueryKey({
        query: { week_start_date: weekStart },
      }),
    })
  }, [queryClient, weekStart])

  const createMutation = useMutation({
    ...timesheetsPayrollPayRunsCreateCreateMutation(),
    onSuccess: () => {
      toast.success('Pay run created')
      invalidate()
    },
    onError: (error) => toast.error(apiErrorMessage(error, 'Could not create the pay run.')),
  })

  const refreshMutation = useMutation({
    ...timesheetsPayrollPayRunsRefreshCreateMutation(),
    onSuccess: (data) => {
      toast.success(`Synced ${data.fetched} pay run${data.fetched === 1 ? '' : 's'} from Xero`)
      invalidate()
    },
    onError: (error) => toast.error(apiErrorMessage(error, 'Could not refresh from Xero.')),
  })

  const postMutation = useMutation({
    ...timesheetsPayrollPostStaffWeekCreateMutation(),
    // Opus: Nothing to unwind. Progress is derived from the run document, and a
    // start that failed wrote no document — so the button cannot be left saying
    // "Posting 0 of N…" while enabled and having started nothing, which is what
    // the local progress state had to be cleared by hand to avoid. A refused
    // duplicate arrives here as a 409 carrying the live run's id, rather than as
    // a fabricated failure the client had to open a stream to discover.
    onError: (error) => toast.error(apiErrorMessage(error, 'Could not start posting to Xero.')),
  })

  const postWeek = useCallback(
    (staffIds: string[]) => {
      if (staffIds.length === 0) {
        toast.error('There are no staff to post for this week.')
        return
      }
      postMutation.mutate(
        { body: { staff_ids: staffIds, week_start_date: weekStart } },
        {
          // Opus: The response IS the run's opening document, so the panel shows
          // "0 of N" without waiting for a push. No stream URL to follow: the
          // stream is already open and keyed by organisation.
          onSuccess: (started) => {
            queryClient.setQueryData<PayrollRunsOut>(timesheetsPayrollRunsRetrieveQueryKey(), {
              post: started.run,
            })
          },
        },
      )
    },
    [postMutation, queryClient, weekStart],
  )

  function reportOutcome(finishedRun: PayrollPostRunOut): void {
    invalidate()
    // Opus: The one moment the Xero read pays for itself: the operator has just
    // written to payroll and the next question is always whether it landed.
    void statusQuery.refetch()
    if (finishedRun.status === 'failed') {
      // Opus: The batch-level message verbatim, because it names the fix — "delete
      // the draft pay run for 2026-07-13, then post again" is the whole of what
      // an operator needs. This is the sentence the old shape published and then
      // never delivered: `error` counted as terminal, so the stream closed
      // before the `done` the client keyed "finished" off, and a real failure
      // read as "the run ended without reporting an outcome".
      toast.error(finishedRun.message ?? `Posting failed.${UNKNOWN_OUTCOME_ADVICE}`)
      return
    }
    if (finishedRun.failed === 0) {
      toast.success(
        `Posted ${finishedRun.successful} staff member${finishedRun.successful === 1 ? '' : 's'} to Xero. ` +
          'Xero may take a minute or two to finish recalculating payslips.',
      )
      return
    }
    // Opus: Not a toast that disappears: a failed staff member is work the operator
    // still has to do, and the rows below carry the reason for each one.
    toast.error(
      `${finishedRun.failed} of ${finishedRun.successful + finishedRun.failed} staff failed to post — see the rows below`,
    )
  }

  return {
    payRun,
    payRunState,
    postableWeekStart: payRunsQuery.data?.next_postable_week_start_date ?? null,
    isLoading: payRunsQuery.isPending,
    loadFailed: payRunsQuery.isError && payRunsQuery.data === undefined,
    createPayRun: () => createMutation.mutate({ body: { week_start_date: weekStart } }),
    isCreating: createMutation.isPending,
    refreshPayRuns: () => refreshMutation.mutate({}),
    isRefreshing: refreshMutation.isPending,
    postWeek,
    isPosting,
    progress,
    results,
    hasPosted,
    postingStatus: statusQuery.data?.staff,
    postingStatusFailed: statusQuery.isError,
    isCheckingXero: statusQuery.isFetching,
    checkXero: () => void statusQuery.refetch(),
  }
}
