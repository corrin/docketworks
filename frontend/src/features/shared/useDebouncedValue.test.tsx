import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useDebouncedValue } from './useDebouncedValue'

describe('useDebouncedValue', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('holds the initial value until the delay elapses', () => {
    const { result } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: 'a' },
    })
    expect(result.current).toBe('a')
  })

  it('adopts the latest value only after the delay, discarding intermediate values', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: 'a' },
    })

    rerender({ value: 'ab' })
    void act(() => vi.advanceTimersByTime(100))
    rerender({ value: 'abc' })
    void act(() => vi.advanceTimersByTime(100))
    // The first change's timer never fired — restarting on every keystroke
    // is the whole point of a debounce.
    expect(result.current).toBe('a')

    void act(() => vi.advanceTimersByTime(200))
    expect(result.current).toBe('abc')
  })

  it('clears a pending timer on unmount', () => {
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout')
    const { unmount } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: 'a' },
    })
    unmount()
    expect(clearSpy).toHaveBeenCalled()
  })
})
