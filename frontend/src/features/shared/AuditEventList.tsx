import { formatDateTime } from '@/lib/format'

/**
 * The fields every domain's event schema shares (the server's AuditEventOut);
 * EntryEventOut, PurchaseOrderEventOut and TimesheetEventOut all satisfy it.
 */
export interface AuditEvent {
  id: string
  timestamp: string
  staff_name: string
  description: string
  changes: ReadonlyArray<{ field_name: string; old_value: string; new_value: string }>
}

interface Props {
  events: ReadonlyArray<AuditEvent>
  /** Ids are `${prefix}-list` and `${prefix}-event-${event.id}`. */
  automationIdPrefix: string
  emptyLabel: string
}

/** One history list for every audit trail: newest first as the server orders
    it (this component re-sorts nothing), actor, time, sentence, change rows. */
export function AuditEventList({ events, automationIdPrefix, emptyLabel }: Props) {
  if (events.length === 0) {
    return <p className="text-sm text-slate-500">{emptyLabel}</p>
  }
  return (
    <ul className="flex flex-col gap-3" data-automation-id={`${automationIdPrefix}-list`}>
      {events.map((event) => (
        <li
          key={event.id}
          data-automation-id={`${automationIdPrefix}-event-${event.id}`}
          className="rounded-md border border-slate-200 p-3 text-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-slate-800">{event.staff_name}</span>
            <time className="text-xs text-slate-500" dateTime={event.timestamp}>
              {formatDateTime(event.timestamp)}
            </time>
          </div>
          <p className="mt-1 whitespace-pre-wrap break-words text-slate-700">{event.description}</p>
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
  )
}
