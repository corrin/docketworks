import { useLayoutEffect, useRef, type RefObject } from 'react'

/**
 * The newest value of a prop or callback, for a reader that runs outside
 * render: a timer, an observer or DnD callback, an effect registered once.
 *
 * Written in the layout phase, never during render. A render-phase write
 * (`ref.current = value` in the component body) is what the `react(refs)` rule
 * forbids: concurrent React can run a render it never commits, and a ref that
 * render wrote then holds a value the tree never showed. Layout rather than
 * passive because a child's passive effect runs before its parent's, while
 * every layout effect of a commit runs before any passive one — so a reader
 * declared later in the same component, in a child, or in a callback always
 * sees the committed value.
 */
export function useLatest<T>(value: T): RefObject<T> {
  const ref = useRef(value)
  useLayoutEffect(() => {
    ref.current = value
  })
  return ref
}
