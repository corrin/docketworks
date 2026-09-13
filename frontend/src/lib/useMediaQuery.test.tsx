import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useMediaQuery } from './useMediaQuery'

/** A MediaQueryList the test can flip, in place of jsdom's missing matchMedia. */
function stubMatchMedia(initialMatches: boolean) {
  const listeners = new Set<() => void>()
  let matches = initialMatches
  const list = {
    get matches() {
      return matches
    },
    addEventListener: (_type: 'change', listener: () => void) => {
      listeners.add(listener)
    },
    removeEventListener: (_type: 'change', listener: () => void) => {
      listeners.delete(listener)
    },
  }
  vi.stubGlobal('matchMedia', () => list)
  return {
    flip: (next: boolean) => {
      matches = next
      for (const listener of listeners) listener()
    },
    listenerCount: () => listeners.size,
  }
}

describe('useMediaQuery', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads the current match and follows change events', () => {
    // The board picks its desktop or mobile layout from this; a hook that
    // stopped listening, or read a stale copy, would leave the wrong layout
    // mounted after a resize across the breakpoint.
    const media = stubMatchMedia(false)
    const { result } = renderHook(() => useMediaQuery('(min-width: 1024px)'))
    expect(result.current).toBe(false)

    act(() => media.flip(true))
    expect(result.current).toBe(true)
  })

  it('unsubscribes on unmount', () => {
    // A listener left behind fires into an unmounted tree on every resize.
    const media = stubMatchMedia(true)
    const { unmount } = renderHook(() => useMediaQuery('(min-width: 1024px)'))
    expect(media.listenerCount()).toBe(1)
    unmount()
    expect(media.listenerCount()).toBe(0)
  })
})
