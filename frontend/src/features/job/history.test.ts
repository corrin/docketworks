import { describe, expect, it } from 'vitest'

import {
  costlineDescription,
  costlineKindClass,
  formatDelta,
  timelineKind,
  timelineTypeLabel,
  TIMELINE_BADGE_CLASS,
  TIMELINE_DOT_CLASS,
} from './history'
import { timelineEntry as entry } from './history.test-fixtures'

describe('timelineKind', () => {
  it('names the three kinds the backend emits', () => {
    expect(timelineKind(entry({ entry_type: 'event' }))).toBe('event')
    expect(timelineKind(entry({ entry_type: 'costline_created' }))).toBe('costline_created')
    expect(timelineKind(entry({ entry_type: 'costline_updated' }))).toBe('costline_updated')
  })

  it('refuses an entry type it has no rendering for', () => {
    expect(() => timelineKind(entry({ entry_type: 'invoice_posted' }))).toThrow(
      "Unknown timeline entry type: 'invoice_posted'",
    )
  })

  it('gives every kind its own dot and badge colour', () => {
    const dots = Object.values(TIMELINE_DOT_CLASS)
    const badges = Object.values(TIMELINE_BADGE_CLASS)
    expect(new Set(dots).size).toBe(dots.length)
    expect(new Set(badges).size).toBe(badges.length)
  })
})

describe('timelineTypeLabel', () => {
  it('titles a job event by its event type', () => {
    expect(timelineTypeLabel(entry({ event_type: 'manual_note' }))).toBe('Manual Note')
  })

  it('calls an untyped job event General', () => {
    expect(timelineTypeLabel(entry({ event_type: null }))).toBe('General')
  })

  it('separates a cost-line update from a creation', () => {
    // v1 rendered costline_updated as a blue "General" job event, because it
    // only ever tested entry_type against 'costline_created'.
    expect(timelineTypeLabel(entry({ entry_type: 'costline_created', event_type: null }))).toBe(
      'Costline Created',
    )
    expect(timelineTypeLabel(entry({ entry_type: 'costline_updated', event_type: null }))).toBe(
      'Costline Updated',
    )
  })
})

describe('costlineDescription', () => {
  it('names the cost set and the line kind', () => {
    expect(
      costlineDescription(
        entry({ entry_type: 'costline_created', cost_set_kind: 'estimate', costline_kind: 'time' }),
      ),
    ).toBe('Estimate - time')
  })

  it('has nothing to say about a job event', () => {
    expect(costlineDescription(entry())).toBeNull()
  })
})

describe('costlineKindClass', () => {
  it('colours each cost-line kind differently', () => {
    const classes = ['time', 'material', 'adjust'].map(costlineKindClass)
    expect(new Set(classes).size).toBe(3)
  })

  it('falls back to the neutral badge for a kind it does not know', () => {
    expect(costlineKindClass('freight')).toBe('bg-gray-100 text-gray-700')
  })
})

describe('formatDelta', () => {
  it('writes one key: value line per field', () => {
    expect(formatDelta({ name: 'Gate frame', order_number: 'A1' })).toBe(
      'name: Gate frame\norder_number: A1',
    )
  })

  it('stringifies a null value rather than dropping the field', () => {
    expect(formatDelta({ notes: null })).toBe('notes: null')
  })

  it('says so when there is no delta at all', () => {
    expect(formatDelta(null)).toBe('No data')
    expect(formatDelta({})).toBe('No data')
  })
})

describe('formatDelta — nested values', () => {
  it('json-encodes an object rather than showing [object Object]', () => {
    expect(formatDelta({ ext_refs: { staff_id: 'staff-1' } })).toBe(
      'ext_refs: {"staff_id":"staff-1"}',
    )
  })

  it('json-encodes an array too', () => {
    expect(formatDelta({ tags: ['urgent', 'rework'] })).toBe('tags: ["urgent","rework"]')
  })
})
