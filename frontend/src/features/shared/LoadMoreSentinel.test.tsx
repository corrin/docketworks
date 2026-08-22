import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { intersect, observingCount } from '@/test/intersection-observer'
import { LoadMoreSentinel } from './LoadMoreSentinel'

const baseProps = {
  automationId: 'Things-load-more',
  noun: 'things',
  shown: 50,
  total: 120,
  isFetchingNextPage: false,
  isFetchNextPageError: false,
}

describe('LoadMoreSentinel', () => {
  it('shows the running count and a Load more button while pages remain', async () => {
    const onLoadMore = vi.fn()
    const user = userEvent.setup()
    render(<LoadMoreSentinel {...baseProps} hasNextPage onLoadMore={onLoadMore} />)

    expect(screen.getByText('Showing 50 of 120 things')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Load more' }))
    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('keeps the count but drops the button once every page is loaded', () => {
    render(
      <LoadMoreSentinel
        {...baseProps}
        shown={120}
        hasNextPage={false}
        onLoadMore={() => undefined}
      />,
    )

    expect(screen.getByText('Showing 120 of 120 things')).toBeVisible()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('disables the button and says so while the next page is in flight', () => {
    render(
      <LoadMoreSentinel
        {...baseProps}
        hasNextPage
        isFetchingNextPage
        onLoadMore={() => undefined}
      />,
    )

    expect(screen.getByRole('button', { name: 'Loading more...' })).toBeDisabled()
  })

  it('reports a failed next page and retries it on demand, not on scroll', () => {
    const onLoadMore = vi.fn()
    render(
      <LoadMoreSentinel {...baseProps} hasNextPage isFetchNextPageError onLoadMore={onLoadMore} />,
    )

    expect(screen.getByText('Loading more failed.')).toBeVisible()
    // A failed page must not be retried every time the foot scrolls into view.
    expect(observingCount()).toBe(0)
    screen.getByRole('button', { name: 'Retry' }).click()
    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('holds the Retry button while the retried page is in flight', () => {
    render(
      <LoadMoreSentinel
        {...baseProps}
        hasNextPage
        isFetchNextPageError
        isFetchingNextPage
        onLoadMore={() => undefined}
      />,
    )

    // The query keeps its error status until the retry resolves, so this
    // branch is what the user sees during the retry; a second click would
    // cancel the request in flight.
    expect(screen.getByRole('button', { name: 'Retrying...' })).toBeDisabled()
  })

  it('renders nothing for an empty list', () => {
    const { container } = render(
      <LoadMoreSentinel
        {...baseProps}
        shown={0}
        total={0}
        hasNextPage={false}
        onLoadMore={() => undefined}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('loads the next page when it scrolls into view, and only when one remains', () => {
    const onLoadMore = vi.fn()
    const { rerender, unmount } = render(
      <LoadMoreSentinel {...baseProps} hasNextPage onLoadMore={onLoadMore} />,
    )

    intersect(false)
    expect(onLoadMore).not.toHaveBeenCalled()
    intersect(true)
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    // In flight: a second intersection must not double-fetch.
    rerender(
      <LoadMoreSentinel {...baseProps} hasNextPage isFetchingNextPage onLoadMore={onLoadMore} />,
    )
    intersect(true)
    expect(onLoadMore).toHaveBeenCalledTimes(1)

    unmount()
    expect(observingCount()).toBe(0)
  })
})
