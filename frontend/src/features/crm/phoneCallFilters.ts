import type { CrmPhoneCallsListData } from '@/api'

/** The four triage queues the calls page offers. */
export type CallsTab = 'recent' | 'unmatched' | 'unlinked' | 'all'

export const CALLS_TABS: readonly CallsTab[] = ['recent', 'unmatched', 'unlinked', 'all']

/** The direction filter's vocabulary, which is the wire's own. */
export type DirectionFilter = NonNullable<NonNullable<CrmPhoneCallsListData['query']>['direction']>

/** The option text for each direction. The `Record<DirectionFilter, …>`
    annotation is what makes the compiler demand an entry for every direction
    the wire declares. */
export const DIRECTION_LABELS: Record<DirectionFilter, string> = {
  all: 'All directions',
  inbound: 'Inbound',
  outbound: 'Outbound',
  internal: 'Internal',
  unknown: 'Unknown',
}

const DIRECTION_FILTER_ORDER = ['all', 'inbound', 'outbound', 'internal', 'unknown'] as const

/**
 * Fable: the labels record and the order list check each other, so a direction
 * added to the wire cannot reach the select without an option. The record's
 * annotation demands a label for it; this alias demands a place in the order,
 * and stops compiling when the exclusion leaves anything behind.
 *
 * Deriving the order from `Object.keys(DIRECTION_LABELS)` was rejected:
 * `Object.keys` is typed `string[]`, so it needs a cast back to the union —
 * and a cast is exactly the silent gap this is here to close.
 */
type AssertNoneMissing<T extends never> = T
export type EveryDirectionIsOffered = AssertNoneMissing<
  Exclude<DirectionFilter, (typeof DIRECTION_FILTER_ORDER)[number]>
>

export const DIRECTION_FILTERS: readonly DirectionFilter[] = DIRECTION_FILTER_ORDER

/** A direction a call can actually have. `all` is the filter's "no filter",
    never a value the wire sends back on a record. */
export type CallDirection = Exclude<DirectionFilter, 'all'>

const CALL_DIRECTIONS: readonly CallDirection[] = DIRECTION_FILTER_ORDER.filter(
  (direction) => direction !== 'all',
)

/**
 * A call's direction as the reader sees it, from the same labels the filter
 * offers.
 *
 * Throws on a direction the wire does not declare: the column carries
 * `Direction.choices` with an `unknown` member, so a fifth value means the
 * wire changed, and rendering it as "Unknown" would hide that behind a label
 * the provider's own unknown already uses.
 */
export function callDirectionLabel(direction: string): string {
  const known = CALL_DIRECTIONS.find((candidate) => candidate === direction)
  if (known === undefined) {
    throw new Error(`Unknown call direction: '${direction}'`)
  }
  return DIRECTION_LABELS[known]
}

interface QueueMeta {
  /** The tab button's text, which is narrower than the heading. */
  tab: string
  title: string
  description: string
}

/** What each queue is called and what it is for, shown above its rows. */
export const QUEUE_META: Record<CallsTab, QueueMeta> = {
  recent: {
    tab: 'Recent Calls',
    title: 'Recent Calls',
    description: 'Newest imported calls. The provider sync runs about every five minutes.',
  },
  unmatched: {
    tab: 'Unmatched',
    title: 'Unmatched Calls',
    description:
      'Assign these numbers to companies or people so future and historical calls land in the right CRM history.',
  },
  unlinked: {
    tab: 'Needs Job Link',
    title: 'Matched Calls Needing Job Link',
    description: 'These calls already belong to a company but have not been linked to a job.',
  },
  all: {
    tab: 'All Calls',
    title: 'All Calls',
    description: 'Audit and search across imported calls.',
  },
}

/** The user's tab and filter choices, before they become query parameters. */
export interface PhoneCallFilters {
  tab: CallsTab
  direction: DirectionFilter
  recordingsOnly: boolean
  q: string
}

type PhoneCallQuery = NonNullable<CrmPhoneCallsListData['query']>

/**
 * The tab-and-filter state as list query parameters.
 *
 * Fable: a filter left at its default is OMITTED rather than sent explicitly,
 * so it stays out of the query key — a page that spelled every default would
 * cache each combination separately and refetch on a filter change that
 * changes nothing. `page` is never set here: the infinite query supplies it,
 * and a base-query `page` would fight the page param the generated queryFn
 * injects.
 */
export function phoneCallQueryFor({
  tab,
  direction,
  recordingsOnly,
  q,
}: PhoneCallFilters): PhoneCallQuery {
  const query: PhoneCallQuery =
    tab === 'unmatched'
      ? { company_match: 'unmatched' }
      : tab === 'unlinked'
        ? { company_match: 'matched', job_link: 'unlinked' }
        : { company_match: 'all', job_link: 'all' }
  if (direction !== 'all') query.direction = direction
  if (recordingsOnly) query.has_recording = true
  const search = q.trim()
  if (search !== '') query.q = search
  return query
}
