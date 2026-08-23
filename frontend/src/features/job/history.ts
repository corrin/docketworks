import type { TimelineEntryOut } from '@/api'
import { formatEventType } from '@/lib/format'

/** The three shapes a timeline entry takes, from `get_job_timeline`. */
export type TimelineKind = 'event' | 'costline_created' | 'costline_updated'

const TIMELINE_KINDS: readonly TimelineKind[] = ['event', 'costline_created', 'costline_updated']

/**
 * The entry's rendering kind. Throws on an entry type the tab has no
 * rendering for: v1 instead treated every non-`costline_created` entry as a
 * job event, which is how `costline_updated` came to render as a blue
 * "General" event nobody could explain.
 */
export function timelineKind(entry: TimelineEntryOut): TimelineKind {
  const known = TIMELINE_KINDS.find((candidate) => candidate === entry.entry_type)
  if (known === undefined) {
    throw new Error(`Unknown timeline entry type: '${entry.entry_type}'`)
  }
  return known
}

/** The timeline dot's colour — one per kind, so a glance separates them. */
export const TIMELINE_DOT_CLASS: Record<TimelineKind, string> = {
  event: 'bg-blue-600',
  costline_created: 'bg-green-600',
  costline_updated: 'bg-amber-600',
}

/** The type badge's colour, matching its dot. */
export const TIMELINE_BADGE_CLASS: Record<TimelineKind, string> = {
  event: 'bg-blue-100 text-blue-700',
  costline_created: 'bg-green-100 text-green-700',
  costline_updated: 'bg-amber-100 text-amber-700',
}

const TIMELINE_KIND_LABEL: Record<TimelineKind, string> = {
  event: 'General',
  costline_created: 'Costline Created',
  costline_updated: 'Costline Updated',
}

/**
 * The type badge's text: a job event is titled by its own event type, and a
 * cost-line entry by what happened to the line. "General" is the label for a
 * job event the backend recorded without an event type.
 */
export function timelineTypeLabel(entry: TimelineEntryOut): string {
  const kind = timelineKind(entry)
  if (kind !== 'event' || entry.event_type === null) {
    return TIMELINE_KIND_LABEL[kind]
  }
  return formatEventType(entry.event_type)
}

/** "Estimate - time" for a cost-line entry; a job event has no cost set. */
export function costlineDescription(entry: TimelineEntryOut): string | null {
  const { cost_set_kind: costSetKind, costline_kind: kind } = entry
  if (costSetKind === null || kind === null) {
    return null
  }
  return `${formatEventType(costSetKind)} - ${kind}`
}

/** The three kinds a cost line takes, from `CostLine.KIND_CHOICES`. */
export type CostlineKind = 'time' | 'material' | 'adjust'

const COSTLINE_KINDS: readonly CostlineKind[] = ['time', 'material', 'adjust']

/**
 * The entry's cost-line kind. Throws on a kind the tab has no badge for,
 * exactly as `timelineKind` does: the column's choices are a fixed triple, so
 * a fourth value means the wire changed, and a neutral badge would render
 * that change as an ordinary row nobody looks at twice.
 */
export function costlineKind(kind: string): CostlineKind {
  const known = COSTLINE_KINDS.find((candidate) => candidate === kind)
  if (known === undefined) {
    throw new Error(`Unknown cost-line kind: '${kind}'`)
  }
  return known
}

/** The cost-line kind badge's colour — one per kind, as the dots are. */
export const COSTLINE_KIND_CLASS: Record<CostlineKind, string> = {
  time: 'bg-purple-100 text-purple-700',
  material: 'bg-orange-100 text-orange-700',
  adjust: 'bg-pink-100 text-pink-700',
}

/**
 * One delta value as text. Scalars are stringified rather than JSON-encoded:
 * the reader is comparing two columns of the same fields, and quoting every
 * string would only add noise. Objects and arrays are the exception — a job
 * delta can carry a nested value, and `String(value)` renders it as the
 * useless `[object Object]`.
 */
function deltaValue(value: unknown): string {
  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value)
  }
  return String(value)
}

/**
 * A delta side as one `key: value` line per field, for the undo panel's
 * Before/After.
 */
export function formatDelta(record: { [key: string]: unknown } | null): string {
  if (record === null) {
    return 'No data'
  }
  const lines = Object.entries(record).map(([key, value]) => `${key}: ${deltaValue(value)}`)
  if (lines.length === 0) {
    return 'No data'
  }
  return lines.join('\n')
}
