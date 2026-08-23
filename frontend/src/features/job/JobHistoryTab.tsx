import { useState } from 'react'
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { ChevronDown, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  crmPhoneCallsListOptions,
  getFullJobOptions,
  jobJobsTimelineRetrieveOptions,
  jobJobsTimelineRetrieveQueryKey,
  jobJobsUndoChangeCreateMutation,
  jobRestJobsEventsCreateMutation,
  type TimelineEntryOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { meQueryOptions } from '@/features/auth'
import { PhoneCallTable } from '@/features/crm'
import { QueryState } from '@/features/shared/QueryState'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { formatDateTime } from '@/lib/format'

import {
  costlineDescription,
  costlineKindClass,
  formatDelta,
  timelineKind,
  timelineTypeLabel,
  TIMELINE_BADGE_CLASS,
  TIMELINE_DOT_CLASS,
} from './history'

const ID = 'JobHistoryTab'

/**
 * The change this entry would undo, or null when there is none to offer.
 * `can_undo` and `change_id` are independently nullable on the wire, and the
 * backend's `_undo_info` already owns the schema-version question — v1
 * re-checked `schema_version === 1` here and disagreed with it.
 */
function undoableChangeId(entry: TimelineEntryOut): string | null {
  if (entry.can_undo !== true) return null
  return entry.change_id
}

interface JobHistoryTabProps {
  jobId: string
}

/**
 * The job's History tab: the unified timeline (job events merged with
 * cost-line creations and updates), a manual event write, per-entry undo of
 * a recorded delta, and the phone calls linked to this job.
 *
 * Add Event, Undo and the linked-calls panel are office-staff only, matching
 * their `office_auth` endpoints — v1 showed all three to everyone and let the
 * request 403.
 */
export function JobHistoryTab({ jobId }: JobHistoryTabProps) {
  const queryClient = useQueryClient()
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const isOfficeStaff = user.is_office_staff

  const [isAddEventOpen, setIsAddEventOpen] = useState(false)
  const [description, setDescription] = useState('')
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(new Set())

  const timeline = useQuery(jobJobsTimelineRetrieveOptions({ path: { job_id: jobId } }))
  const phoneCalls = useQuery({
    ...crmPhoneCallsListOptions({ query: { job: jobId, page: 1, page_size: 50 } }),
    enabled: isOfficeStaff,
  })

  const timelineKey = jobJobsTimelineRetrieveQueryKey({ path: { job_id: jobId } })
  const jobKey = getFullJobOptions({ path: { job_id: jobId } }).queryKey

  const addEvent = useMutation({
    ...jobRestJobsEventsCreateMutation(),
    onSuccess: () => {
      setDescription('')
      setIsAddEventOpen(false)
      void queryClient.invalidateQueries({ queryKey: timelineKey })
      // The job's own version moved with the write, so the detail cache the
      // header's inline edits read is re-fetched rather than left behind a
      // stale ETag.
      void queryClient.invalidateQueries({ queryKey: jobKey })
      toast.success('Event added')
    },
    onError: (error) => {
      // The concurrency interceptor already toasts 412/428 with a Retry.
      if (!isConcurrencyError(error)) {
        toast.error(apiErrorMessage(error, 'Failed to add event.'))
      }
    },
  })

  const undoChange = useMutation({
    ...jobJobsUndoChangeCreateMutation(),
    onSuccess: () => {
      setExpandedIds(new Set())
      void queryClient.invalidateQueries({ queryKey: timelineKey })
      // v1 called window.location.reload() here, throwing away every other
      // tab's cache to refresh the header; invalidating the job detail is the
      // same refresh without the round trip.
      void queryClient.invalidateQueries({ queryKey: jobKey })
      toast.success('Change undone successfully')
    },
    onError: (error) => {
      // A refused undo means this timeline no longer describes the job — a 412
      // says so outright — so the entries are re-read either way.
      void queryClient.invalidateQueries({ queryKey: timelineKey })
      if (!isConcurrencyError(error)) {
        toast.error(apiErrorMessage(error, 'Failed to undo change.'))
      }
    },
  })

  const toggleExpanded = (entryId: string) => {
    setExpandedIds((current) => {
      const next = new Set(current)
      if (next.has(entryId)) {
        next.delete(entryId)
      } else {
        next.add(entryId)
      }
      return next
    })
  }

  const callsPage = phoneCalls.data
  const entries = timeline.data === undefined ? [] : timeline.data.timeline

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Job History</h2>
            <p className="text-sm text-gray-600">
              View and manage the history of events for this job.
            </p>
          </div>
          {isOfficeStaff && (
            <Button
              type="button"
              data-automation-id={`${ID}-add-event-toggle`}
              onClick={() => setIsAddEventOpen(!isAddEventOpen)}
            >
              <ChevronDown className={isAddEventOpen ? 'rotate-180' : undefined} />
              Add Event
            </Button>
          )}
        </div>

        {isOfficeStaff && (
          <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="text-lg font-medium text-gray-900">Linked Phone Calls</h3>
              <div className="flex items-center gap-2">
                <QueryState
                  isPending={phoneCalls.isPending}
                  isError={phoneCalls.isError}
                  // The table below owns the Retry; a second one beside the
                  // count would offer the same refetch twice.
                  loadingNode={<span className="text-xs text-gray-500">Counting…</span>}
                  errorNode={<span className="text-xs text-red-600">Count unavailable</span>}
                >
                  {callsPage !== undefined && (
                    <span className="text-xs text-gray-500">
                      Showing {callsPage.results.length} of {callsPage.count}
                    </span>
                  )}
                </QueryState>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  data-automation-id={`${ID}-phone-calls-refresh`}
                  disabled={phoneCalls.isFetching}
                  onClick={() => void phoneCalls.refetch()}
                >
                  <RefreshCw className={phoneCalls.isFetching ? 'animate-spin' : undefined} />
                  Refresh
                </Button>
              </div>
            </div>
            {/* No onCallUpdated: the table's own link/unlink invalidate the
                phone-call list this query reads, so the server answer replaces
                the rows. v1 patched the row it held and drifted from the list. */}
            <PhoneCallTable
              isPending={phoneCalls.isPending}
              isError={phoneCalls.isError}
              onRetry={() => void phoneCalls.refetch()}
              rows={callsPage === undefined ? undefined : callsPage.results}
              emptyLabel="No linked phone calls"
              allowJobLinking
            />
          </section>
        )}

        {isOfficeStaff && isAddEventOpen && (
          <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="mb-4 text-lg font-medium text-gray-900">Add New Event</h3>
            <label
              className="mb-2 block text-sm font-medium text-gray-700"
              htmlFor={`${ID}-event-description`}
            >
              Event Description
            </label>
            <textarea
              id={`${ID}-event-description`}
              data-automation-id={`${ID}-event-description`}
              rows={3}
              className={INPUT_CLASS}
              placeholder="Describe what happened..."
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <div className="mt-4 flex justify-end gap-3">
              <Button
                type="button"
                variant="outline"
                data-automation-id={`${ID}-add-event-cancel`}
                onClick={() => {
                  setDescription('')
                  setIsAddEventOpen(false)
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                data-automation-id={`${ID}-add-event-submit`}
                disabled={description.trim() === '' || addEvent.isPending}
                onClick={() =>
                  addEvent.mutate({
                    path: { job_id: jobId },
                    body: { description: description.trim() },
                  })
                }
              >
                {addEvent.isPending ? 'Adding...' : 'Add Event'}
              </Button>
            </div>
          </section>
        )}

        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-6 text-lg font-medium text-gray-900">Event Timeline</h3>
          <QueryState
            isPending={timeline.isPending}
            isError={timeline.isError}
            onRetry={() => void timeline.refetch()}
            errorLabel="Failed to load the job timeline."
            loadingNode={
              <div className="py-12 text-center">
                <div className="mx-auto mb-2 h-8 w-8 animate-spin rounded-full border-b-2 border-blue-600" />
                <p className="text-gray-500">Loading events...</p>
              </div>
            }
          >
            {entries.length === 0 ? (
              <div data-automation-id={`${ID}-empty`} className="py-12 text-center">
                <h4 className="mb-1 text-sm font-medium text-gray-900">No events recorded yet</h4>
                <p className="text-sm text-gray-500">
                  Get started by adding the first event to this job.
                </p>
              </div>
            ) : (
              <div data-automation-id={`${ID}-timeline`} className="space-y-6">
                {entries.map((entry) => {
                  const kind = timelineKind(entry)
                  const costline = costlineDescription(entry)
                  const changeId = isOfficeStaff ? undoableChangeId(entry) : null
                  const isExpanded = expandedIds.has(entry.id)
                  return (
                    <div
                      // v1 keyed on the id alone, so one cost line's creation
                      // and update — which share an id — collided and React
                      // rendered only the first.
                      key={`${entry.entry_type}-${entry.id}`}
                      data-automation-id={`${ID}-entry-${entry.entry_type}-${entry.id}`}
                      className="flex items-start gap-4"
                    >
                      <div
                        className={`mt-2 h-3 w-3 flex-shrink-0 rounded-full border-2 border-white shadow-sm ${TIMELINE_DOT_CLASS[kind]}`}
                      />
                      <div className="min-w-0 flex-1 rounded-lg border border-gray-200 p-4 shadow-sm">
                        <p className="text-sm leading-relaxed text-gray-900">{entry.description}</p>
                        {costline === null ? null : (
                          <p className="mt-1 text-xs text-gray-600 italic">{costline}</p>
                        )}
                        <div className="mt-3 flex items-center justify-between border-t border-gray-100 pt-3">
                          <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
                            <span className="font-medium">{formatDateTime(entry.timestamp)}</span>
                            <span>•</span>
                            <span
                              className={`rounded-full px-2 py-1 ${TIMELINE_BADGE_CLASS[kind]}`}
                            >
                              {timelineTypeLabel(entry)}
                            </span>
                            {entry.costline_kind === null ? null : (
                              <>
                                <span>•</span>
                                <span
                                  className={`rounded-full px-2 py-1 capitalize ${costlineKindClass(entry.costline_kind)}`}
                                >
                                  {entry.costline_kind}
                                </span>
                              </>
                            )}
                            {entry.staff === null ? null : (
                              <>
                                <span>•</span>
                                <span className="font-medium text-gray-700">{entry.staff}</span>
                              </>
                            )}
                          </div>
                          {changeId !== null && (
                            <button
                              type="button"
                              data-automation-id={`${ID}-undo-toggle-${entry.id}`}
                              className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50"
                              onClick={() => toggleExpanded(entry.id)}
                            >
                              <ChevronDown
                                className={`h-3 w-3 ${isExpanded ? 'rotate-180' : ''}`}
                              />
                              {isExpanded ? 'Hide' : 'Undo'}
                            </button>
                          )}
                        </div>
                        {changeId !== null && isExpanded && (
                          <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
                            <h5 className="mb-3 text-sm font-medium text-gray-900">Undo Change</h5>
                            <p className="text-xs text-gray-600">
                              {entry.undo_description === null
                                ? 'Revert this change'
                                : entry.undo_description}
                            </p>
                            <div className="mt-3 grid grid-cols-2 gap-4">
                              <div>
                                <span className="text-xs font-medium text-red-700">Before:</span>
                                <pre
                                  data-automation-id={`${ID}-undo-before-${entry.id}`}
                                  className="mt-1 rounded border bg-red-50 p-2 text-xs whitespace-pre-wrap text-gray-600"
                                >
                                  {formatDelta(entry.delta_before)}
                                </pre>
                              </div>
                              <div>
                                <span className="text-xs font-medium text-green-700">After:</span>
                                <pre
                                  data-automation-id={`${ID}-undo-after-${entry.id}`}
                                  className="mt-1 rounded border bg-green-50 p-2 text-xs whitespace-pre-wrap text-gray-600"
                                >
                                  {formatDelta(entry.delta_after)}
                                </pre>
                              </div>
                            </div>
                            <div className="mt-4 flex justify-end gap-2">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                data-automation-id={`${ID}-undo-cancel-${entry.id}`}
                                onClick={() => toggleExpanded(entry.id)}
                              >
                                Cancel
                              </Button>
                              <Button
                                type="button"
                                variant="destructive"
                                size="sm"
                                data-automation-id={`${ID}-undo-confirm-${entry.id}`}
                                disabled={undoChange.isPending}
                                onClick={() =>
                                  undoChange.mutate({
                                    path: { job_id: jobId },
                                    body: { change_id: changeId },
                                  })
                                }
                              >
                                {undoChange.isPending ? 'Undoing...' : 'Confirm Undo'}
                              </Button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </QueryState>
        </section>
      </div>
    </div>
  )
}
