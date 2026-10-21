import { useBlocker } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

/**
 * The one unsaved-changes guard every settings screen arms (ADR 0039): three
 * pages carried this block verbatim. TanStack Router blocks when shouldBlockFn
 * returns true, so a confirmed discard is the negation; `disabled` arms it —
 * calling the hook conditionally would break the rules of hooks.
 */
export function useUnsavedChangesGuard(isDirty: boolean): void {
  const { t } = useTranslation('shared')
  useBlocker({
    shouldBlockFn: () => !window.confirm(t('unsavedChanges.prompt')),
    disabled: !isDirty,
    enableBeforeUnload: () => isDirty,
  })
}
