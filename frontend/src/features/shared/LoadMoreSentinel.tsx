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
 * Fable: the list is finite, so the count shows how far the user is whenever
 * there are rows, and loading stops at the last page. The button is the
 * keyboard and screen-reader path; the observer is the same action fired by
 * scrolling. `react-intersection-observer`'s `useInView` is the library
 * shape (ADR 0032) and was rejected because it is not installed and would
 * replace one ten-line effect with a dependency.
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
  // Fable: the callback lives in a ref so the observer is rebuilt only when
  // `canLoad` flips, not on every parent render — a rebuild fires the
  // callback with the current intersection state, and a render landing
  // between fetchNextPage() and the isFetchingNextPage commit would issue a
  // second fetch that cancels the first.
  const onLoadMoreRef = useRef(onLoadMore)
  onLoadMoreRef.current = onLoadMore
  // Fable: after a failure the observer is off — retry is a deliberate
  // click, not a refetch storm every time the foot scrolls into view.
  const canLoad = hasNextPage && !isFetchingNextPage && !isFetchNextPageError

  useEffect(() => {
    if (!canLoad || ref.current === null) return undefined
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        onLoadMoreRef.current()
      }
    })
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [canLoad])

  if (total === 0) return null

  return (
    <div
      ref={ref}
      data-automation-id={automationId}
      className="mt-4 flex items-center gap-4 text-sm text-gray-600"
    >
      {/* aria-live: the Load more button unmounts on the last page, so the
          count is what a screen-reader user hears after the final click. */}
      <span data-automation-id={`${automationId}-count`} aria-live="polite">
        Showing {shown} of {total} {noun}
      </span>
      {isFetchNextPageError ? (
        <span className="flex items-center gap-3 text-red-800">
          Loading more failed.
          {/* Fable: the query keeps its error status while the retry is in
              flight, so this branch stays on screen; a second click would
              cancel the request (cancelRefetch), hence the disabled state. */}
          <button
            type="button"
            data-automation-id={`${automationId}-retry`}
            className="font-medium underline disabled:opacity-50"
            disabled={isFetchingNextPage}
            onClick={onLoadMore}
          >
            {isFetchingNextPage ? 'Retrying...' : 'Retry'}
          </button>
        </span>
      ) : (
        hasNextPage && (
          <button
            type="button"
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
