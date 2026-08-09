import { useEffect, useRef, useState } from 'react'

export const AUTOSAVE_DEBOUNCE_MS = 600

interface AutosaveField {
  value: string
  onChange: (raw: string) => void
  onFocus: () => void
  onBlur: () => void
}

/**
 * Per-cell edit buffer: keystrokes debounce into one commit, blur flushes and
 * cancels the timer (so a debounce-then-blur never double-commits).
 *
 * The displayed value is DERIVED — the local buffer only while DIRTY (typed
 * into since focus), the server value otherwise. Deriving instead of
 * effect-syncing a copy is load-bearing for rollbacks: an optimistic write
 * and its failure rollback can land between two renders, so an effect keyed
 * on the server value never fires (it round-tripped to the same string) and
 * a synced copy would keep the rejected input on screen forever. Tracking
 * dirtiness rather than copying the server value in at focus matters too:
 * focus can arrive in the same tick as a state-updating blur on a sibling
 * cell, when the render-captured server value is still stale.
 *
 * `parse` returns the canonical value to commit, or null to reject; a
 * rejected blur falls back to the server value instead of sending garbage.
 */
export function useAutosaveField(
  serverValue: string,
  commit: (value: string) => void,
  parse: (raw: string) => string | null = (raw) => raw,
  // Server PATCHes dedupe; draft commits never do — a draft's commit is
  // local state plus a guarded POST, and after a failed POST re-committing
  // the SAME value must retry.
  dedupeSends = true,
): AutosaveField {
  const [localValue, setLocalValue] = useState('')
  const [dirty, setDirty] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSentRef = useRef<string | null>(null)
  // The debounce timer fires up to 600ms after its render; a ref keeps the
  // comparison below against the LIVE server value, not the one the closure
  // captured (a stale value could suppress a commit that is not redundant).
  const serverValueRef = useRef(serverValue)
  serverValueRef.current = serverValue

  // Unmount with a pending timer (e.g. the row was deleted mid-typing) must
  // not fire a commit against a line that no longer exists.
  useEffect(
    () => () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    },
    [],
  )

  const cancelTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const dispatch = (raw: string) => {
    const parsed = parse(raw)
    if (parsed === null) return
    if (dedupeSends) {
      // Dedupe only a send that is KNOWN applied (the optimistic cache write
      // is synchronous, so an applied send always shows in serverValue).
      // After a failed PATCH the rollback restores the old serverValue, and
      // the same value must be sendable again — the retry is the whole point.
      const current = serverValueRef.current
      const knownApplied = parsed === lastSentRef.current && parsed === current
      const untouched = lastSentRef.current === null && parsed === current
      if (knownApplied || untouched) return
    }
    lastSentRef.current = parsed
    commit(parsed)
  }

  return {
    value: dirty ? localValue : serverValue,
    onChange: (raw: string) => {
      setDirty(true)
      setLocalValue(raw)
      cancelTimer()
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        dispatch(raw)
      }, AUTOSAVE_DEBOUNCE_MS)
    },
    onFocus: () => {
      lastSentRef.current = null
    },
    onBlur: () => {
      cancelTimer()
      // An untouched focus/blur commits nothing — a retry is a retype.
      if (dirty) dispatch(localValue)
      setDirty(false)
    },
  }
}
