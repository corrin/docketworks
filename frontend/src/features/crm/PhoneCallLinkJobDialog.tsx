import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companiesJobsRetrieveOptions,
  crmPhoneCallsListQueryKey,
  linkPhoneCallJobMutation,
  type CompanyJobHeader,
  type PhoneCallRecordOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { JobPicker, type JobPickerOption } from '@/features/shared/JobPicker'
import { QueryState } from '@/features/shared/QueryState'

/**
 * The call's current job as the picker's option, or null when it holds none.
 *
 * Fable: throws rather than falling back when a linked call carries no job
 * number. The backend derives job_number from the same row as job, so the
 * pair can only disagree if the list payload is malformed — and a fallback
 * would draw a badge reading "Job #" (ADR 0015).
 */
export function linkedJobOption(call: PhoneCallRecordOut): JobPickerOption | null {
  if (call.job === null) return null
  if (call.job_number === null) {
    throw new Error(`Phone call ${call.id} is linked to job ${call.job} but carries no job number`)
  }
  return {
    id: call.job,
    job_number: call.job_number,
    name: call.job_name,
    company_name: call.company_name,
    status: call.job_status,
  }
}

function toPickerOption(job: CompanyJobHeader): JobPickerOption {
  return {
    id: job.job_id,
    job_number: job.job_number,
    name: job.name,
    company_name: job.company === null ? null : job.company.name,
    status: job.status,
  }
}

interface PhoneCallLinkJobDialogProps {
  /** The call being linked, or null when the dialog is closed. */
  call: PhoneCallRecordOut | null
  onClose: () => void
}

/**
 * Link one phone call to one of its company's jobs.
 *
 * The picker is fed the company's jobs and nothing else: the service refuses
 * a job belonging to any other company with a 400, so a background search
 * across all jobs would only offer choices that cannot be saved.
 */
export function PhoneCallLinkJobDialog({ call, onClose }: PhoneCallLinkJobDialogProps) {
  return (
    <Dialog
      open={call !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      {/* Keyed on the call so the picked job resets between calls; mounted
          only while open so the body can take a non-null call and read its
          company without a nullable dance at every use. */}
      {call !== null && <LinkJobDialogBody key={call.id} call={call} onClose={onClose} />}
    </Dialog>
  )
}

function LinkJobDialogBody({ call, onClose }: { call: PhoneCallRecordOut; onClose: () => void }) {
  const companyId = call.company
  if (companyId === null) {
    throw new Error(`Phone call ${call.id} has no company, so it has no jobs to link`)
  }
  const queryClient = useQueryClient()
  const contentRef = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState<JobPickerOption | null>(linkedJobOption(call))

  const jobs = useQuery(companiesJobsRetrieveOptions({ path: { company_id: companyId } }))
  const options = useMemo(
    () => (jobs.data === undefined ? [] : jobs.data.results.map(toPickerOption)),
    [jobs.data],
  )

  const link = useMutation({
    ...linkPhoneCallJobMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: crmPhoneCallsListQueryKey() })
      toast.success('Phone call linked to job')
      onClose()
    },
    onError: (error) => toast.error(apiErrorMessage(error, 'Failed to link phone call')),
  })

  return (
    <DialogContent
      ref={contentRef}
      className="sm:max-w-lg"
      data-automation-id="PhoneCallTable-link-dialog"
      onOpenAutoFocus={(event) => {
        // Fable: Radix's default focuses the first focusable child, which here
        // is the picker's trigger — and the picker opens itself on keyboard
        // focus, so the dialog would arrive with its list already down and the
        // user's first click on the trigger would CLOSE it. Focusing the
        // dialog itself keeps focus inside for keyboard and screen-reader
        // users while leaving the picker shut until it is asked for.
        event.preventDefault()
        contentRef.current?.focus()
      }}
    >
      <DialogHeader>
        <DialogTitle>Link Phone Call To Job</DialogTitle>
      </DialogHeader>
      {/* isPending is false deliberately: the picker draws its own "Jobs are
          loading…" row, so gating it behind the shared loading block would
          replace an open, usable control with a bare line of text. The error
          half of the same gate is still the shared one. */}
      <QueryState
        isPending={false}
        isError={jobs.isError}
        onRetry={() => void jobs.refetch()}
        errorLabel={`Failed to load ${call.company_name}'s jobs.`}
      >
        <div className="rounded-md border border-slate-200">
          <JobPicker
            automationIdPrefix="PhoneCallTable-job"
            ariaLabel="Job for this phone call"
            jobs={options}
            selected={selected}
            disabled={link.isPending}
            loading={jobs.isPending}
            placeholder="Select job"
            triggerLabel={(job) => (job === null ? '' : `#${job.job_number} - ${job.name}`)}
            typedSearchLimit={null}
            commitOnTab={false}
            onSelect={setSelected}
          />
        </div>
      </QueryState>
      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          data-automation-id="PhoneCallTable-cancel-job-link"
          onClick={onClose}
        >
          Cancel
        </Button>
        <Button
          type="button"
          data-automation-id="PhoneCallTable-save-job-link"
          disabled={selected === null || link.isPending}
          onClick={() => {
            if (selected === null) return
            link.mutate({ path: { call_id: call.id }, body: { job: selected.id } })
          }}
        >
          Save
        </Button>
      </DialogFooter>
    </DialogContent>
  )
}
