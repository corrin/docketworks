import { render, renderHook } from '@testing-library/react'
import { useEffect, type RefObject } from 'react'
import { describe, expect, it } from 'vitest'

import { useLatest } from './useLatest'

function Reader({ latest, seen }: { latest: RefObject<string>; seen: string[] }) {
  useEffect(() => {
    seen.push(latest.current)
  })
  return null
}

function Parent({ value, seen }: { value: string; seen: string[] }) {
  const latest = useLatest(value)
  return <Reader latest={latest} seen={seen} />
}

describe('useLatest', () => {
  it("a child's passive effect reads the value of the commit it runs in", () => {
    // A child's passive effects run before the parent's, so a write in the
    // parent's passive effect would leave the child one render behind. Moving
    // the write out of the layout phase would turn ['a', 'b'] into ['a', 'a'].
    const seen: string[] = []
    const { rerender } = render(<Parent value="a" seen={seen} />)
    rerender(<Parent value="b" seen={seen} />)
    expect(seen).toEqual(['a', 'b'])
  })

  it('a callback captured on the first render reads the newest value', () => {
    // The pattern's whole purpose: a timer or observer callback registered
    // once must see the current prop, not the one its closure captured.
    // Returning a fresh ref per render, or never writing it, would read 'a'.
    const captured: { read?: () => string } = {}
    const { rerender } = renderHook(
      ({ value }) => {
        const latest = useLatest(value)
        captured.read ??= () => latest.current
      },
      { initialProps: { value: 'a' } },
    )
    rerender({ value: 'b' })
    if (captured.read === undefined) throw new Error('the first render did not capture a reader')
    expect(captured.read()).toBe('b')
  })
})
