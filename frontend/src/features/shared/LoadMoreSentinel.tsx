import { useEffect, useRef } from 'react'

interface LoadMoreSentinelProps {
  automationId: string
  /** Plural noun for the count line: "Showing 50 of 120 people". */
  noun: string
  shown: number
  total: number
  hasNextPage: boolean
  isFetchingNextPage: boolean
  isFetchNextPageError: boolean
  /** Fetch the next page; also the retry after a failed one. */
  onLoadMore: () => void
}

/**
 * The foot of an infinite-scroll list: a running count and a Load more
 * button that also fires itself when scrolled into view.
 *
 * Fable: "load more, auto-triggered" rather than feed-style infinite scroll.
 * These lists are finite, so the total is always on screen, loading stops at
 * the last page and the page footer stays reachable; the button is the
 * keyboard and screen-reader path and the E2E handle, never a fallback that
 * could be removed once the observer works.
 */
export function LoadMoreSentinel({
  automationId,
  noun,
  shown,
  total,
  hasNextPage,
  isFetchingNextPage,
  isFetchNextPageError,
  onLoadMore,
}: LoadMoreSentinelProps) {
  const ref = useRef<HTMLDivElement>(null)
  // After a failure the observer is off: retry is a deliberate click, not
  // a refetch storm every time the foot of the list scrolls into view.
  const canLoad = hasNextPage && !isFetchingNextPage && !isFetchNextPageError

  useEffect(() => {
    if (!canLoad || ref.current === null) return undefined
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        onLoadMore()
      }
    })
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [canLoad, onLoadMore])

  if (total === 0) return null

  return (
    <div
      ref={ref}
      data-automation-id={automationId}
      className="mt-4 flex items-center gap-4 text-sm text-gray-600"
    >
      <span data-automation-id={`${automationId}-count`}>
        Showing {shown} of {total} {noun}
      </span>
      {isFetchNextPageError ? (
        <span className="flex items-center gap-3 text-red-800">
          Loading more failed.
          <button type="button" className="font-medium underline" onClick={onLoadMore}>
            Retry
          </button>
        </span>
      ) : (
        hasNextPage && (
          <button
            type="button"
            data-automation-id={`${automationId}-button`}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            disabled={isFetchingNextPage}
            onClick={onLoadMore}
          >
            {isFetchingNextPage ? 'Loading more...' : 'Load more'}
          </button>
        )
      )}
    </div>
  )
}
