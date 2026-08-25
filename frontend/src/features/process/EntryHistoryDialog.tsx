import { useQuery } from '@tanstack/react-query'

import { processEntriesHistoryListOptions, type EntryOut } from '@/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { QueryState } from '@/features/shared/QueryState'
import { formatDateTime } from '@/lib/format'

interface Props {
  /** The entry whose history is shown, or null while the dialog is closed. */
  entry: EntryOut | null
  onClose: () => void
}

/** An entry's audit trail: every ProcessEvent recorded against it, newest
    first (the endpoint's own ordering — this dialog re-sorts nothing). */
export function EntryHistoryDialog({ entry, onClose }: Props) {
  return (
    <Dialog
      open={entry !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      {/* Keyed on the entry so a stale history list never bleeds into the
          next row's dialog; mounted only while open so the body can take a
          non-null entry with no nullable dance at every use. */}
      {entry !== null && <HistoryBody key={entry.id} entry={entry} />}
    </Dialog>
  )
}

function HistoryBody({ entry }: { entry: EntryOut }) {
  const historyQuery = useQuery(processEntriesHistoryListOptions({ path: { entry_id: entry.id } }))
  const events = historyQuery.data ?? []

  return (
    <DialogContent
      className="max-h-[80vh] overflow-y-auto sm:max-w-2xl"
      data-automation-id="EntryHistoryDialog-content"
    >
      <DialogHeader>
        <DialogTitle>Entry history</DialogTitle>
      </DialogHeader>
      <QueryState
        isPending={historyQuery.isPending}
        isError={historyQuery.isError}
        onRetry={() => void historyQuery.refetch()}
        loadingLabel="Loading history..."
        errorLabel="Failed to load this entry's history."
      >
        {events.length === 0 ? (
          <p className="text-sm text-slate-500">No history recorded yet.</p>
        ) : (
          <ul className="flex flex-col gap-3" data-automation-id="EntryHistoryDialog-list">
            {events.map((event) => (
              <li
                key={event.id}
                data-automation-id={`EntryHistoryDialog-event-${event.id}`}
                className="rounded-md border border-slate-200 p-3 text-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-800">{event.staff_name}</span>
                  <span className="text-xs text-slate-500">{formatDateTime(event.timestamp)}</span>
                </div>
                <p className="mt-1 text-slate-700">{event.description}</p>
                {event.changes.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1 text-xs text-slate-600">
                    {event.changes.map((change) => (
                      <li key={change.field_name}>
                        <span className="font-medium">{change.field_name}</span>:{' '}
                        {change.old_value || '—'} &rarr; {change.new_value || '—'}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </DialogContent>
  )
}
