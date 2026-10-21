import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  crmPhoneCallsListQueryKey,
  unlinkPhoneCallJobMutation,
  type PhoneCallRecordOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { AudioPlayer } from '@/features/shared/AudioPlayer'
import { ListTable } from '@/features/shared/ListTable'
import { formatDateTime } from '@/lib/format'
import { i18n } from '@/lib/i18n'

import { callDirectionLabel } from './phoneCallFilters'
import { linkedJobOption, PhoneCallLinkJobDialog } from './PhoneCallLinkJobDialog'

/** `45s` under a minute, `1m 07s` above it — the seconds pad so a column of
    durations lines up. */
function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (minutes === 0) return i18n.t('crm:phoneCallTable.durationSeconds', { seconds: remainder })
  return i18n.t('crm:phoneCallTable.durationMinutes', {
    minutes,
    seconds: String(remainder).padStart(2, '0'),
  })
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
  /** Offered only where the caller can host the assign panel; a call with no
      company is otherwise simply reported as unmatched. */
  onAssignNumber?: (call: PhoneCallRecordOut) => void
}

const HEAD_CLASS = 'px-3 py-2 text-left font-semibold text-gray-700'

/**
 * The one phone-call table: the calls page's triage queues and the job
 * History tab's linked calls draw the same seven columns.
 *
 * Linking is unconditional. It was a prop until both surfaces turned out to
 * want it — a call linked to the wrong job is corrected wherever it is
 * noticed, which is what v1 did too — and a flag no caller ever sets false is
 * a branch no test exercises honestly.
 */
export function PhoneCallTable({
  isPending,
  isError,
  onRetry,
  rows,
  emptyLabel,
  onAssignNumber,
}: PhoneCallTableProps) {
  const { t } = useTranslation('crm')
  const queryClient = useQueryClient()
  const [linkTarget, setLinkTarget] = useState<PhoneCallRecordOut | null>(null)

  const unlink = useMutation({
    ...unlinkPhoneCallJobMutation(),
    onSuccess: () => {
      // The refetch is authoritative rather than the response: unlinking moves
      // the call into the "needs job link" queue, which is a different row set.
      void queryClient.invalidateQueries({ queryKey: crmPhoneCallsListQueryKey() })
      toast.success(t('phoneCallTable.unlinked'))
    },
    onError: (error) => toast.error(apiErrorMessage(error, t('phoneCallTable.unlinkFailed'))),
  })

  return (
    <>
      <ListTable
        isPending={isPending}
        isError={isError}
        onRetry={onRetry}
        loadingLabel={t('phoneCallTable.loading')}
        errorLabel={t('phoneCallTable.loadFailed')}
        rows={rows}
        emptyLabel={emptyLabel}
        automationId="PhoneCallTable"
        head={
          <tr className="border-b border-gray-200 bg-slate-50">
            <th scope="col" className={HEAD_CLASS}>
              {t('phoneCallTable.columns.dateTime')}
            </th>
            <th scope="col" className={HEAD_CLASS}>
              {t('phoneCallTable.columns.numberCompany')}
            </th>
            <th scope="col" className={HEAD_CLASS}>
              {t('phoneCallTable.columns.ourNumber')}
            </th>
            <th scope="col" className={HEAD_CLASS}>
              {t('phoneCallTable.columns.direction')}
            </th>
            <th scope="col" className={HEAD_CLASS}>
              {t('phoneCallTable.columns.duration')}
            </th>
            <th scope="col" className={HEAD_CLASS}>
              {t('phoneCallTable.columns.job')}
            </th>
            <th scope="col" className={HEAD_CLASS}>
              {t('phoneCallTable.columns.recording')}
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
                {call.attempt_count > 1 && (
                  // One row stands for N indistinguishable unrecorded ring
                  // attempts the provider logged for this call.
                  <span
                    data-automation-id={`PhoneCallTable-attempts-${call.id}`}
                    className="ml-2 rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-600"
                  >
                    {t('phoneCallTable.attempts', { count: call.attempt_count })}
                  </span>
                )}
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
                        {t('phoneCallTable.assignNumber')}
                      </Button>
                    )}
                </div>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                {call.our_number || '—'}
              </td>
              <td className="px-3 py-2">
                <span className="rounded-full border border-gray-300 px-2 py-0.5 text-xs text-gray-700">
                  {callDirectionLabel(call.direction)}
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
                      {t('phoneCallTable.linkedJob', { number: linkedJob.job_number })}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      data-automation-id={`PhoneCallTable-change-job-${call.id}`}
                      onClick={() => setLinkTarget(call)}
                    >
                      {t('phoneCallTable.change')}
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
                      {t('phoneCallTable.unlink')}
                    </Button>
                    <div className="basis-full text-xs text-gray-500">{linkedJob.name}</div>
                  </div>
                ) : call.company !== null ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-automation-id={`PhoneCallTable-link-job-${call.id}`}
                    onClick={() => setLinkTarget(call)}
                  >
                    {t('phoneCallTable.linkJob')}
                  </Button>
                ) : (
                  // A call with no company: the link endpoint would 400, since
                  // the job must belong to the call's company.
                  <span className="text-xs text-gray-500">
                    {t('phoneCallTable.assignCompanyFirst')}
                  </span>
                )}
              </td>
              <td className="min-w-64 px-3 py-2">
                {url === null || call.recording === null ? (
                  <span className="text-xs text-gray-500">{t('phoneCallTable.noRecording')}</span>
                ) : (
                  // The length shown is the recording's own, measured when it
                  // was archived — not duration_seconds, which is the provider's
                  // per-minute billing figure for the call.
                  <AudioPlayer
                    src={url}
                    durationMs={call.recording.duration_ms}
                    automationId={`PhoneCallTable-recording-${call.id}`}
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
