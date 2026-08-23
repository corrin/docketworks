import type { TimelineEntryOut } from '@/api'

/**
 * One timeline entry, defaulting to a staff-written job event. Shared by
 * the History tab's tests and the timeline helpers': TimelineEntryOut has
 * twenty-one fields, nineteen of which are null on most entries, so a second
 * copy of this builder drifts the moment the wire contract gains a field.
 */
export function timelineEntry(overrides: Partial<TimelineEntryOut> = {}): TimelineEntryOut {
  return {
    can_undo: null,
    change_id: null,
    cost_set_kind: null,
    costline_kind: null,
    created_at: null,
    delta_after: null,
    delta_before: null,
    delta_checksum: null,
    delta_meta: null,
    description: 'Job created',
    entry_type: 'event',
    event_type: 'manual_note',
    id: 'event-1',
    quantity: null,
    schema_version: null,
    staff: 'Alex Smith',
    timestamp: '2026-08-09T02:30:00Z',
    total_cost: null,
    total_rev: null,
    undo_description: null,
    unit_cost: null,
    unit_rev: null,
    updated_at: null,
    ...overrides,
  }
}
