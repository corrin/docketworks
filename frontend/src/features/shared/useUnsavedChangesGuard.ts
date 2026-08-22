import { useBlocker } from '@tanstack/react-router'

export const UNSAVED_CHANGES_PROMPT = 'You have unsaved changes. Discard them and leave this page?'

/**
 * The one unsaved-changes guard every settings screen arms (ADR 0039): three
 * pages carried this block verbatim. TanStack Router blocks when shouldBlockFn
 * returns true, so a confirmed discard is the negation; `disabled` arms it —
 * calling the hook conditionally would break the rules of hooks.
 */
export function useUnsavedChangesGuard(isDirty: boolean): void {
  useBlocker({
    shouldBlockFn: () => !window.confirm(UNSAVED_CHANGES_PROMPT),
    disabled: !isDirty,
    enableBeforeUnload: () => isDirty,
  })
}
