import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { LoadMoreSentinel } from './LoadMoreSentinel'

/**
 * jsdom has no layout, so intersection is driven by hand: every observer
 * still observing is in `live`, and `intersect` fires them — like the real
 * API, a disconnected observer never fires again.
 */
const live = new Set<FakeIntersectionObserver>()

class FakeIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly scrollMargin = ''
  readonly thresholds: readonly number[] = []
  private readonly callback: IntersectionObserverCallback
  private target: Element | null = null

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    live.add(this)
  }

  observe(target: Element): void {
    this.target = target
  }

  unobserve(): void {}

  disconnect(): void {
    live.delete(this)
  }

  takeRecords(): IntersectionObserverEntry[] {
    return []
  }

  fire(isIntersecting: boolean): void {
    if (this.target === null) throw new Error('fired before observe()')
    const rect = this.target.getBoundingClientRect()
    this.callback(
      [
        {
          isIntersecting,
          target: this.target,
          time: 0,
          intersectionRatio: isIntersecting ? 1 : 0,
          boundingClientRect: rect,
          intersectionRect: rect,
          rootBounds: null,
        },
      ],
      this,
    )
  }
}

function intersect(isIntersecting: boolean): void {
  for (const observer of live) observer.fire(isIntersecting)
}

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
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver)
    const onLoadMore = vi.fn()
    render(
      <LoadMoreSentinel {...baseProps} hasNextPage isFetchNextPageError onLoadMore={onLoadMore} />,
    )

    expect(screen.getByText('Loading more failed.')).toBeVisible()
    // A failed page must not be retried every time the foot scrolls into view.
    expect(live.size).toBe(0)
    screen.getByRole('button', { name: 'Retry' }).click()
    expect(onLoadMore).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
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
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver)
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
    expect(live.size).toBe(0)
    vi.unstubAllGlobals()
  })
})
