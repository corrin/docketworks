import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  crmPhoneCallsListQueryKey,
  unlinkPhoneCallJobMutation,
  type PhoneCallRecordOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { formatDateTime } from '@/lib/format'

import { linkedJobOption, PhoneCallLinkJobDialog } from './PhoneCallLinkJobDialog'

/** `45s` under a minute, `1m 07s` above it — the seconds pad so a column of
    durations lines up. */
function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (minutes === 0) return `${remainder}s`
  return `${minutes}m ${String(remainder).padStart(2, '0')}s`
}

function formatDirection(direction: string): string {
  if (direction === 'inbound') return 'Inbound'
  if (direction === 'outbound') return 'Outbound'
  if (direction === 'internal') return 'Internal'
  return 'Unknown'
}

/** The recording's playable URL, or null when there is nothing to play. */
function recordingUrl(call: PhoneCallRecordOut): string | null {
  if (call.recording === null) return null
  return call.recording.download_url
}

interface PhoneCallTableProps {
  isPending: boolean
  isError: boolean
  onRetry: () => void
  rows: readonly PhoneCallRecordOut[] | undefined
  emptyLabel: string
  /** False on surfaces that only report a call's job (the job's own History
      tab), where changing the link would move the call off the page. */
  allowJobLinking: boolean
  /** Offered only where the caller can host the assign panel; a call with no
      company is otherwise simply reported as unmatched. */
  onAssignNumber?: (call: PhoneCallRecordOut) => void
}

const HEAD_CLASS = 'px-3 py-2 text-left font-semibold text-gray-700'

/**
 * The one phone-call table: the calls page's triage queues and the job
 * History tab's linked calls draw the same seven columns, and linking is a
 * prop rather than a second component.
 */
export function PhoneCallTable({
  isPending,
  isError,
  onRetry,
  rows,
  emptyLabel,
  allowJobLinking,
  onAssignNumber,
}: PhoneCallTableProps) {
  const queryClient = useQueryClient()
  const [linkTarget, setLinkTarget] = useState<PhoneCallRecordOut | null>(null)

  const unlink = useMutation({
    ...unlinkPhoneCallJobMutation(),
    onSuccess: () => {
      // The refetch is authoritative rather than the response: unlinking moves
      // the call into the "needs job link" queue, which is a different row set.
      void queryClient.invalidateQueries({ queryKey: crmPhoneCallsListQueryKey() })
      toast.success('Phone call unlinked from job')
    },
    onError: (error) => toast.error(apiErrorMessage(error, 'Failed to unlink phone call')),
  })

  return (
    <>
      <ListTable
        isPending={isPending}
        isError={isError}
        onRetry={onRetry}
        loadingLabel="Loading calls..."
        errorLabel="Failed to load calls."
        rows={rows}
        emptyLabel={emptyLabel}
        automationId="PhoneCallTable"
        head={
          <tr className="border-b border-gray-200 bg-slate-50">
            <th scope="col" className={HEAD_CLASS}>
              Date &amp; Time
            </th>
            <th scope="col" className={HEAD_CLASS}>
              Number / Company
            </th>
            <th scope="col" className={HEAD_CLASS}>
              Our Number
            </th>
            <th scope="col" className={HEAD_CLASS}>
              Direction
            </th>
            <th scope="col" className={HEAD_CLASS}>
              Duration
            </th>
            <th scope="col" className={HEAD_CLASS}>
              Job
            </th>
            <th scope="col" className={HEAD_CLASS}>
              Recording
            </th>
          </tr>
        }
        renderRow={(call) => {
          const linkedJob = linkedJobOption(call)
          const url = recordingUrl(call)
          return (
            <tr
              key={call.id}
              data-automation-id={`PhoneCallTable-row-${call.id}`}
              className="border-b border-gray-100"
            >
              <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                {formatDateTime(call.call_datetime)}
              </td>
              <td className="px-3 py-2">
                <div className="font-medium text-gray-900">
                  {call.company_name || call.external_number || '—'}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                  <span>{call.person_name || call.external_number || '—'}</span>
                  {onAssignNumber !== undefined &&
                    call.company === null &&
                    call.external_number !== null && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        data-automation-id={`PhoneCallTable-assign-number-${call.id}`}
                        onClick={() => onAssignNumber(call)}
                      >
                        Assign number
                      </Button>
                    )}
                </div>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                {call.our_number || '—'}
              </td>
              <td className="px-3 py-2">
                <span className="rounded-full border border-gray-300 px-2 py-0.5 text-xs text-gray-700">
                  {formatDirection(call.direction)}
                </span>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                {formatDuration(call.duration_seconds)}
              </td>
              <td className="min-w-48 px-3 py-2">
                {linkedJob !== null ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      data-automation-id={`PhoneCallTable-linked-job-${call.id}`}
                      className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700"
                    >
                      Job #{linkedJob.job_number}
                    </span>
                    {allowJobLinking && (
                      <>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          data-automation-id={`PhoneCallTable-change-job-${call.id}`}
                          onClick={() => setLinkTarget(call)}
                        >
                          Change
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-red-700 hover:text-red-800"
                          data-automation-id={`PhoneCallTable-unlink-job-${call.id}`}
                          disabled={unlink.isPending}
                          onClick={() => unlink.mutate({ path: { call_id: call.id } })}
                        >
                          Unlink
                        </Button>
                      </>
                    )}
                    <div className="basis-full text-xs text-gray-500">{linkedJob.name}</div>
                  </div>
                ) : call.company !== null && allowJobLinking ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-automation-id={`PhoneCallTable-link-job-${call.id}`}
                    onClick={() => setLinkTarget(call)}
                  >
                    Link job
                  </Button>
                ) : (
                  <span className="text-xs text-gray-500">Assign company first</span>
                )}
              </td>
              <td className="min-w-64 px-3 py-2">
                {url === null ? (
                  <span className="text-xs text-gray-500">No recording</span>
                ) : (
                  // preload="none": one <audio> per row means "metadata" makes
                  // the browser fetch every recording on page load — about 2 MB
                  // of audio nobody played. The duration column already comes
                  // from duration_seconds, so there is nothing to preload for.
                  <audio
                    controls
                    preload="none"
                    src={url}
                    data-automation-id={`PhoneCallTable-recording-${call.id}`}
                    className="h-9 w-full max-w-sm"
                  />
                )}
              </td>
            </tr>
          )
        }}
      />
      <PhoneCallLinkJobDialog call={linkTarget} onClose={() => setLinkTarget(null)} />
    </>
  )
}
