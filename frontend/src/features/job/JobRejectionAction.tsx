import { useRef, useState } from 'react'
import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { toast } from 'sonner'

import { apiErrorMessage, jobJobsFinishRetrieveOptions, type JobDetail } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { meQueryOptions } from '@/features/auth'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { formatCurrency } from '@/lib/format'

import { snapshotJob } from './delta'
import { useJobFieldSave } from './useJobFieldSave'

type ActionState =
  | { phase: 'idle' }
  | { phase: 'loading'; reject: boolean }
  | { phase: 'confirm'; reject: boolean; baseline: JobDetail; remaining: number }
  | { phase: 'saving'; reject: boolean }
  | { phase: 'error'; reject: boolean; message: string }

export function JobRejectionAction({ job }: { job: JobDetail }) {
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const queryClient = useQueryClient()
  const [state, setState] = useState<ActionState>({ phase: 'idle' })
  const actionRef = useRef<HTMLButtonElement>(null)
  const busy = useRef(false)
  const { save, discardChanges } = useJobFieldSave(job.id, {
    onRetry: (fresh, changes) => {
      if (typeof changes.rejected_flag !== 'boolean') {
        throw new Error('A rejection retry must include its intended rejection flag')
      }
      void prepare(fresh, changes.rejected_flag)
    },
  })

  async function submit(baseline: JobDetail, reject: boolean) {
    if (busy.current) return
    busy.current = true
    setState({ phase: 'saving', reject })
    try {
      await save(snapshotJob(baseline), {
        rejected_flag: reject,
        job_status: reject ? 'archived' : 'draft',
      })
      setState({ phase: 'idle' })
      toast.success(reject ? 'Job rejected and moved to Archived' : 'Job reopened in Draft')
    } catch (error) {
      // GPT: The shared conflict toast owns Retry. Close the modal so that
      // its focus trap cannot make that action unreachable.
      if (isConcurrencyError(error)) {
        setState({ phase: 'idle' })
        return
      }
      setState({
        phase: 'error',
        reject,
        message: apiErrorMessage(error, 'Failed to save the job.'),
      })
    } finally {
      busy.current = false
    }
  }

  async function prepare(baseline: JobDetail, reject: boolean) {
    if (busy.current) return
    busy.current = true
    discardChanges()
    setState({ phase: 'loading', reject })
    try {
      if (!reject) {
        setState({ phase: 'confirm', reject, baseline, remaining: 0 })
        return
      }
      // GPT: A cached Finish tab can predate invoices. Every rejection attempt
      // reads the server balance again, including a retry after a conflict.
      const finish = await queryClient.fetchQuery({
        ...jobJobsFinishRetrieveOptions({ path: { job_id: job.id } }),
        staleTime: 0,
      })
      const remaining = Number(finish.summary.remaining_to_invoice_excl_gst)
      if (remaining > 0) {
        setState({ phase: 'confirm', reject, baseline, remaining })
        return
      }
    } catch (error) {
      setState({
        phase: 'error',
        reject,
        message: apiErrorMessage(error, "Could not check this job's uninvoiced value."),
      })
      return
    } finally {
      busy.current = false
    }
    await submit(baseline, reject)
  }

  const cancel = () => {
    if (busy.current) return
    discardChanges()
    setState({ phase: 'idle' })
  }

  if (!user.is_office_staff) return null

  const rejecting = state.phase === 'idle' ? !job.rejected_flag : state.reject

  return (
    <>
      <Button
        ref={actionRef}
        type="button"
        variant={job.rejected_flag ? 'outline' : 'destructive'}
        size="sm"
        data-automation-id="JobView-rejection-action"
        disabled={state.phase !== 'idle'}
        onClick={() => void prepare(job, !job.rejected_flag)}
      >
        {state.phase === 'loading'
          ? 'Checking…'
          : state.phase === 'saving'
            ? 'Saving…'
            : job.rejected_flag
              ? 'Reopen job'
              : 'Reject job'}
      </Button>
      {/* Opus: The dialog opens only when there is something to decide. Opening
          it for a check or save that needs no answer left it closing as the next
          click arrived, and Radix swallowed the reopen. */}
      <Dialog
        open={state.phase === 'confirm' || state.phase === 'error'}
        onOpenChange={(open) => {
          if (!open) cancel()
        }}
      >
        <DialogContent
          onCloseAutoFocus={(event) => {
            // GPT: Preflight and confirmation share one controlled dialog. A
            // separate trigger toggle races its transitions, so return focus here.
            event.preventDefault()
            actionRef.current?.focus()
          }}
        >
          <DialogHeader>
            <DialogTitle>{rejecting ? 'Reject job' : 'Reopen job'}</DialogTitle>
            <DialogDescription>
              {rejecting
                ? 'Rejecting this job moves it to Archived.'
                : 'Clearing rejection moves this job back to Draft.'}
            </DialogDescription>
          </DialogHeader>
          {state.phase === 'confirm' && state.reject ? (
            <p data-automation-id="JobView-rejection-warning" className="text-sm text-amber-800">
              This job has {formatCurrency(state.remaining)} excluding GST still to be invoiced. Are
              you sure you want to reject it?
            </p>
          ) : state.phase === 'error' ? (
            <p role="alert" className="text-sm text-red-700">
              {state.message}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              data-automation-id="JobView-rejection-cancel"
              onClick={cancel}
            >
              Cancel
            </Button>
            {state.phase === 'confirm' ? (
              <Button
                type="button"
                variant={state.reject ? 'destructive' : 'default'}
                data-automation-id="JobView-rejection-confirm"
                onClick={() => void submit(state.baseline, state.reject)}
              >
                {state.reject ? 'Reject job' : 'Reopen in Draft'}
              </Button>
            ) : state.phase === 'error' ? (
              <Button
                type="button"
                data-automation-id="JobView-rejection-retry"
                onClick={() => void prepare(job, state.reject)}
              >
                Try again
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
