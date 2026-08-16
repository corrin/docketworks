/**
 * Pay-run state and the posting run for one payroll week.
 *
 * Server state (which pay runs exist, which week may be posted) stays in the
 * Query cache. The only local state is the progress of a run in flight, which
 * is not server state — it is a conversation with a task, and it ends.
 */
import { useCallback, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  streamPayrollPost,
  timesheetsPayrollPayRunsCreateCreateMutation,
  timesheetsPayrollPayRunsRefreshCreateMutation,
  timesheetsPayrollPayRunsRetrieveOptions,
  timesheetsPayrollPayRunsRetrieveQueryKey,
  timesheetsPayrollPostStaffWeekCreateMutation,
  timesheetsPayrollWeekStatusRetrieveOptions,
  timesheetsPayrollWeekStatusRetrieveQueryKey,
  timesheetsWeeklyRetrieveQueryKey,
  type PayrollCompleteEvent,
  type PayRunListItemOut,
  type StaffWeekPostingOut,
} from '@/api'

/** How the selected week stands with payroll, in the words the page shows. */
export type PayRunState = 'draft' | 'posted' | 'missing'

export interface PayrollProgress {
  current: number
  total: number
  staffName: string | null
}

export interface UsePayrollWeekResult {
  payRun: PayRunListItemOut | undefined
  payRunState: PayRunState
  /** The one week the server says may be posted next; null when it cannot say. */
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
  results: PayrollCompleteEvent[]
  /** Set once a post has run this session, so the button can say "Re-post". */
  hasPosted: boolean
  /**
   * What Xero holds for the week, per staff member, beside what we recorded.
   *
   * Undefined until asked for, and on failure. Deliberately NOT merged into the
   * weekly payload: this read calls Xero, and folding it in would blank the
   * grid whenever Xero is unreachable (ADR 0007).
   */
  postingStatus: StaffWeekPostingOut[] | undefined
  postingStatusFailed: boolean
  isCheckingXero: boolean
  /** Ask Xero what it holds for this week. Costs one API call per staff member. */
  checkXero: () => void
}

export function usePayrollWeek(weekStart: string): UsePayrollWeekResult {
  const queryClient = useQueryClient()
  const payRunsQuery = useQuery(timesheetsPayrollPayRunsRetrieveOptions())
  // Never on mount. Xero has no bulk leave endpoint, so this asks
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
  const [progress, setProgress] = useState<PayrollProgress | null>(null)
  const [results, setResults] = useState<PayrollCompleteEvent[]>([])
  const [hasPosted, setHasPosted] = useState(false)
  const [isPosting, setIsPosting] = useState(false)
  // Abort a run's stream if the operator navigates away mid-post; the task
  // keeps going server-side, which is the point of it living there.
  const abortRef = useRef<AbortController | null>(null)

  const payRun = payRunsQuery.data?.pay_runs.find((run) => run.period_start_date === weekStart)
  const payRunState: PayRunState =
    payRun === undefined ? 'missing' : payRun.pay_run_status === 'Posted' ? 'posted' : 'draft'

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: timesheetsPayrollPayRunsRetrieveQueryKey() })
    void queryClient.invalidateQueries({
      queryKey: timesheetsWeeklyRetrieveQueryKey({ query: { start_date: weekStart } }),
    })
    // Invalidate rather than refetch: a disabled query stays disabled, so this
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
    onError: (error) => {
      setIsPosting(false)
      toast.error(apiErrorMessage(error, 'Could not start posting to Xero.'))
    },
  })

  const postWeek = useCallback(
    (staffIds: string[]) => {
      if (staffIds.length === 0) {
        toast.error('There are no staff to post for this week.')
        return
      }
      setIsPosting(true)
      setResults([])
      setProgress({ current: 0, total: staffIds.length, staffName: null })
      postMutation.mutate(
        { body: { staff_ids: staffIds, week_start_date: weekStart } },
        {
          onSuccess: (started) => {
            void consumeRun(started.stream_url)
          },
        },
      )
    },
    // consumeRun is stable for the life of the hook; listing it would need a
    // ref dance that buys nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [postMutation, weekStart],
  )

  async function consumeRun(streamUrl: string): Promise<void> {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      for await (const event of streamPayrollPost(streamUrl, controller.signal)) {
        if (event.event === 'progress') {
          setProgress({ current: event.current, total: event.total, staffName: event.staff_name })
        } else if (event.event === 'complete') {
          setResults((previous) => [...previous, event])
        } else if (event.event === 'error') {
          toast.error(event.message)
        } else if (event.event === 'done') {
          reportOutcome(event.successful, event.failed)
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        toast.error(apiErrorMessage(error, 'Lost contact with the posting run.'))
      }
    } finally {
      setIsPosting(false)
      setProgress(null)
      abortRef.current = null
    }
  }

  function reportOutcome(successful: number, failed: number): void {
    setHasPosted(true)
    invalidate()
    // The one moment the Xero read pays for itself: the operator has just
    // written to payroll and the next question is always whether it landed.
    void statusQuery.refetch()
    if (failed === 0) {
      toast.success(`Posted ${successful} staff member${successful === 1 ? '' : 's'} to Xero`)
      return
    }
    // Not a toast that disappears: a failed staff member is work the operator
    // still has to do, and the rows below carry the reason for each one.
    toast.error(`${failed} of ${successful + failed} staff failed to post — see the rows below`)
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
