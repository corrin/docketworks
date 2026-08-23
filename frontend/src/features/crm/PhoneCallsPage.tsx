import { useState } from 'react'
import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'

import { crmPhoneCallsListInfiniteOptions, type PhoneCallRecordOut } from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { LoadMoreSentinel } from '@/features/shared/LoadMoreSentinel'
import { nextPageParam } from '@/features/shared/nextPageParam'
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from '@/features/shared/useDebouncedValue'

import { AssignCallNumberPanel } from './AssignCallNumberPanel'
import { PhoneCallTable } from './PhoneCallTable'
import {
  CALLS_TABS,
  DIRECTION_FILTERS,
  phoneCallQueryFor,
  QUEUE_META,
  type CallsTab,
  type DirectionFilter,
} from './phoneCallFilters'

const TAB_LABELS: Record<CallsTab, string> = {
  recent: 'Recent Calls',
  unmatched: 'Unmatched',
  unlinked: 'Needs Job Link',
  all: 'All Calls',
}

const DIRECTION_LABELS: Record<DirectionFilter, string> = {
  all: 'All directions',
  inbound: 'Inbound',
  outbound: 'Outbound',
  internal: 'Internal',
  unknown: 'Unknown',
}

const ID = 'PhoneCallsPage'

/**
 * The CRM calls page: four triage queues over the imported phone-provider
 * calls, with linking to a job and claiming a number for a company.
 *
 * Plain buttons for the tabs rather than Radix Tabs: `components/ui` carries
 * no tabs primitive, and four buttons that set one piece of state do not
 * justify adding one — the job detail's own tab bar is the same shape.
 *
 * v1 also subscribed to a `dataFreshness` channel here so a provider sync
 * pushed new rows in. v2 has no such channel, and Refresh plus the
 * post-mutation invalidation cover what it was for.
 */
export function PhoneCallsPage() {
  const [tab, setTab] = useState<CallsTab>('recent')
  const [searchInput, setSearchInput] = useState('')
  const q = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS)
  const [direction, setDirection] = useState<DirectionFilter>('all')
  const [recordingsOnly, setRecordingsOnly] = useState(false)
  const [assignTarget, setAssignTarget] = useState<PhoneCallRecordOut | null>(null)

  const calls = useInfiniteQuery({
    ...crmPhoneCallsListInfiniteOptions({
      query: phoneCallQueryFor({ tab, direction, recordingsOnly, q }),
    }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    // A refetch of an infinite query re-requests every loaded page in series,
    // so a window-focus refetch of a list scrolled ten pages deep is ten
    // requests for nothing. Invalidation after a mutation still refetches all
    // pages, which is the one time the rows are known to have changed.
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  })
  const rows = calls.data?.pages.flatMap((page) => page.results)
  const lastPage = calls.data?.pages.at(-1)
  const queue = QUEUE_META[tab]

  return (
    <div className="min-h-screen p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Calls</h1>
          <p className="mt-1 text-sm text-gray-600">Recent phone-provider calls and CRM triage.</p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-automation-id={`${ID}-refresh`}
          disabled={calls.isFetching}
          onClick={() => void calls.refetch()}
        >
          <RefreshCw className={calls.isFetching ? 'animate-spin' : undefined} />
          Refresh
        </Button>
      </div>

      <nav className="mt-4 flex space-x-1 overflow-x-auto border-b border-gray-200">
        {CALLS_TABS.map((candidate) => (
          <button
            key={candidate}
            type="button"
            data-automation-id={`${ID}-tab-${candidate}`}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === candidate
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
            onClick={() => setTab(candidate)}
          >
            {TAB_LABELS[candidate]}
          </button>
        ))}
      </nav>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input
          type="text"
          data-automation-id={`${ID}-search`}
          placeholder="Search number, company, person, job, or description"
          value={searchInput}
          autoComplete="off"
          aria-label="Search calls"
          className="w-full max-w-md rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
          onChange={(event) => setSearchInput(event.target.value)}
        />
        <select
          data-automation-id={`${ID}-direction`}
          aria-label="Direction"
          value={direction}
          className={`${INPUT_CLASS} w-auto`}
          onChange={(event) => {
            const chosen = DIRECTION_FILTERS.find((option) => option === event.target.value)
            if (chosen === undefined) {
              throw new Error(`Unknown call direction filter: ${event.target.value}`)
            }
            setDirection(chosen)
          }}
        >
          {DIRECTION_FILTERS.map((option) => (
            <option key={option} value={option}>
              {DIRECTION_LABELS[option]}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            data-automation-id={`${ID}-with-recording`}
            checked={recordingsOnly}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            onChange={(event) => setRecordingsOnly(event.target.checked)}
          />
          With recording
        </label>
      </div>

      <div className="mt-6">
        <h2 className="text-base font-semibold text-gray-900">{queue.title}</h2>
        <p className="text-sm text-gray-500">{queue.description}</p>
      </div>

      {calls.isRefetchError && (
        <div className="mt-4 flex items-center gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {/* A failed next page is LoadMoreSentinel's to report; this banner is
              only for a background refetch of the rows already on screen. */}
          <span>Refresh failed — showing the last loaded rows.</span>
          <button
            type="button"
            className="font-medium underline"
            onClick={() => void calls.refetch()}
          >
            Retry
          </button>
        </div>
      )}

      <PhoneCallTable
        isPending={calls.isPending}
        // A failed FIRST load is the error state; an errored background refetch
        // keeps the keepPreviousData table on screen, with the banner above
        // owning visibility.
        isError={calls.isError && calls.data === undefined}
        onRetry={() => void calls.refetch()}
        rows={rows}
        emptyLabel="No calls found"
        allowJobLinking
        onAssignNumber={setAssignTarget}
      />

      {rows !== undefined && lastPage !== undefined && (
        <LoadMoreSentinel
          automationId={`${ID}-load-more`}
          noun="calls"
          shown={rows.length}
          total={lastPage.count}
          hasNextPage={calls.hasNextPage}
          isFetchingNextPage={calls.isFetchingNextPage}
          isFetchNextPageError={calls.isFetchNextPageError}
          onLoadMore={() => void calls.fetchNextPage()}
        />
      )}

      {assignTarget !== null && (
        <AssignCallNumberPanel call={assignTarget} onClose={() => setAssignTarget(null)} />
      )}
    </div>
  )
}
