import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { jobTimesheetEntriesHistoryRetrieveOptions } from '@/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AuditEventList } from '@/features/shared/AuditEventList'
import { QueryState } from '@/features/shared/QueryState'
import { formatDateLong } from '@/lib/format'

interface Props {
  staffId: string
  date: string
  open: boolean
  onClose: () => void
}

/** A staff member's timesheet audit trail for one day: every TimesheetEvent
    recorded against their entries that day, newest first (the endpoint's own
    ordering). Per day rather than per row so a deleted entry's events are
    still reachable from the screen they were made on. */
export function TimesheetHistoryDialog({ staffId, date, open, onClose }: Props) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      {/* Keyed on the day so a stale list never bleeds into the next day's
          dialog; mounted only while open. */}
      {open && <HistoryBody key={`${staffId}:${date}`} staffId={staffId} date={date} />}
    </Dialog>
  )
}

function HistoryBody({ staffId, date }: { staffId: string; date: string }) {
  const { t } = useTranslation('timesheet')
  const historyQuery = useQuery(
    jobTimesheetEntriesHistoryRetrieveOptions({ query: { staff_id: staffId, date } }),
  )
  // An action made away from the workshop says so, in the words the office
  // reads everywhere else; one at the workshop reads plain.
  const events = (historyQuery.data ?? []).map((event) => ({
    id: event.id,
    timestamp: event.timestamp,
    staff_name: event.staff_name,
    changes: event.changes,
    description: event.trusted
      ? event.description
      : t('history.awayFromWorkshop', { description: event.description }),
  }))

  return (
    <DialogContent
      className="max-h-[80vh] overflow-y-auto sm:max-w-2xl"
      data-automation-id="TimesheetHistoryDialog-content"
    >
      <DialogHeader>
        <DialogTitle>{t('history.title', { date: formatDateLong(date) })}</DialogTitle>
      </DialogHeader>
      <QueryState
        isPending={historyQuery.isPending}
        isError={historyQuery.isError}
        onRetry={() => void historyQuery.refetch()}
        loadingLabel={t('history.loading')}
        errorLabel={t('history.loadFailed')}
      >
        <AuditEventList
          events={events}
          automationIdPrefix="TimesheetHistoryDialog"
          emptyLabel={t('history.empty')}
        />
      </QueryState>
    </DialogContent>
  )
}
