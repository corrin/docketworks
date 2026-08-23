import type { CrmPhoneCallsListData } from '@/api'

/** The four triage queues the calls page offers. */
export type CallsTab = 'recent' | 'unmatched' | 'unlinked' | 'all'

export const CALLS_TABS: readonly CallsTab[] = ['recent', 'unmatched', 'unlinked', 'all']

/** The direction filter's vocabulary, which is the wire's own. */
export type DirectionFilter = NonNullable<NonNullable<CrmPhoneCallsListData['query']>['direction']>

export const DIRECTION_FILTERS: readonly DirectionFilter[] = [
  'all',
  'inbound',
  'outbound',
  'internal',
  'unknown',
]

interface QueueMeta {
  title: string
  description: string
}

/** What each queue is for, shown above its rows. */
export const QUEUE_META: Record<CallsTab, QueueMeta> = {
  recent: {
    title: 'Recent Calls',
    description: 'Newest imported calls. The provider sync runs about every five minutes.',
  },
  unmatched: {
    title: 'Unmatched Calls',
    description:
      'Assign these numbers to companies or people so future and historical calls land in the right CRM history.',
  },
  unlinked: {
    title: 'Matched Calls Needing Job Link',
    description: 'These calls already belong to a company but have not been linked to a job.',
  },
  all: {
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
