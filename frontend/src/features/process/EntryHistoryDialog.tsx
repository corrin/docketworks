import { useQuery } from '@tanstack/react-query'

import { processEntriesHistoryListOptions, type EntryOut } from '@/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AuditEventList } from '@/features/shared/AuditEventList'
import { QueryState } from '@/features/shared/QueryState'

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
        <AuditEventList
          events={events}
          automationIdPrefix="EntryHistoryDialog"
          emptyLabel="No history recorded yet."
        />
      </QueryState>
    </DialogContent>
  )
}
