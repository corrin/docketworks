import { useRef, useState } from 'react'

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
 * The displayed value is DERIVED — the local buffer only while editing, the
 * server value otherwise. Deriving instead of effect-syncing a copy is
 * load-bearing for rollbacks: an optimistic write and its failure rollback
 * can land between two renders, so an effect keyed on the server value never
 * fires (it round-tripped to the same string) and a synced copy would keep
 * the rejected input on screen forever.
 *
 * `parse` returns the canonical value to commit, or null to reject; a
 * rejected blur falls back to the server value instead of sending garbage.
 */
export function useAutosaveField(
  serverValue: string,
  commit: (value: string) => void,
  parse: (raw: string) => string | null = (raw) => raw,
): AutosaveField {
  const [localValue, setLocalValue] = useState(serverValue)
  const [editing, setEditing] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSentRef = useRef<string | null>(null)

  const cancelTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const dispatch = (raw: string) => {
    const parsed = parse(raw)
    if (parsed === null) return
    if (parsed === serverValue && lastSentRef.current === null) return
    if (parsed === lastSentRef.current) return
    lastSentRef.current = parsed
    commit(parsed)
  }

  return {
    value: editing ? localValue : serverValue,
    onChange: (raw: string) => {
      setLocalValue(raw)
      cancelTimer()
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        dispatch(raw)
      }, AUTOSAVE_DEBOUNCE_MS)
    },
    onFocus: () => {
      setEditing(true)
      setLocalValue(serverValue)
      lastSentRef.current = null
    },
    onBlur: () => {
      cancelTimer()
      dispatch(localValue)
      setEditing(false)
    },
  }
}
