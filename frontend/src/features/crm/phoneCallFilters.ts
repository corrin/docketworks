import type { CrmPhoneCallsListData } from '@/api'
import { i18n } from '@/lib/i18n'

/** The four triage queues the calls page offers. */
export type CallsTab = 'recent' | 'unmatched' | 'unlinked' | 'all'

export const CALLS_TABS: readonly CallsTab[] = ['recent', 'unmatched', 'unlinked', 'all']

/** The direction filter's vocabulary, which is the wire's own. */
export type DirectionFilter = NonNullable<NonNullable<CrmPhoneCallsListData['query']>['direction']>

/** The option text for a direction. The catalogue is typed, so a direction the
    wire declares without a `crm:phoneCalls.direction.*` entry does not compile. */
export function directionLabel(direction: DirectionFilter): string {
  return i18n.t(`crm:phoneCalls.direction.${direction}`)
}

const DIRECTION_FILTER_ORDER = ['all', 'inbound', 'outbound', 'internal', 'unknown'] as const

/**
 * Fable: the typed catalogue and the order list check each other, so a direction
 * added to the wire cannot reach the select without an option. The catalogue's
 * key type demands a label for it; this alias demands a place in the order,
 * and stops compiling when the exclusion leaves anything behind.
 *
 * Deriving the order from a list of the catalogue's keys was rejected:
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
  return directionLabel(known)
}

interface QueueMeta {
  /** The tab button's text, which is narrower than the heading. */
  tab: string
  title: string
  description: string
}

/** What a queue is called and what it is for, shown above its rows. The
    catalogue holds a `tab`, `title` and `description` under each queue's key. */
export function queueMeta(tab: CallsTab): QueueMeta {
  return {
    tab: i18n.t(`crm:phoneCalls.queues.${tab}.tab`),
    title: i18n.t(`crm:phoneCalls.queues.${tab}.title`),
    description: i18n.t(`crm:phoneCalls.queues.${tab}.description`),
  }
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
