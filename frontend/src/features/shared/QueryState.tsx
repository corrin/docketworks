import type { ReactNode } from 'react'

interface QueryStateProps {
  isPending: boolean
  isError: boolean
  /** Omit for a static "Reload the page." message; pass the query's
      refetch for a working Retry button. Ignored when `errorNode` is given. */
  onRetry?: () => void
  /** Text-block rendering (page-level "Loading X..." / "Failed to load X.")
      — the default for most callers. Ignored once the matching *Node prop
      is given. */
  loadingLabel?: string
  /** The loading element's data-automation-id — must unmount (not just
      hide) once loaded, since an E2E wait on it can require leaving the
      tree. Only supply where a spec asserts one; ignored with `loadingNode`. */
  loadingAutomationId?: string
  errorLabel?: string
  /** Full markup override for callers whose loading/error state is not the
      page-level text block (a spinner, a compact card notice) — the STATE
      MACHINE (pending → error → children) is still the shared, tested part
      even where the visual shell legitimately differs. */
  loadingNode?: ReactNode
  errorNode?: ReactNode
  /** Rendered only once neither pending nor errored. */
  children: ReactNode
}

/**
 * The one owner of the pending/error gate every query-backed page or panel
 * repeats at its top: show loading, then error (Retry or a static "Reload
 * the page."), otherwise render children — reused standalone (a detail
 * page, a card, a grid) and internally by `ListTable` (`features/shared/
 * ListTable.tsx`) for its rows-table cousin. The default rendering is the
 * plain page-level text block; `loadingNode`/`errorNode` override it for
 * callers with a bespoke loading UI (a spinner) without reimplementing the
 * gate itself.
 */
export function QueryState({
  isPending,
  isError,
  onRetry,
  loadingLabel,
  loadingAutomationId,
  errorLabel,
  loadingNode,
  errorNode,
  children,
}: QueryStateProps) {
  if (isPending) {
    return (
      loadingNode ?? (
        <div data-automation-id={loadingAutomationId} className="mt-8 text-gray-500">
          {loadingLabel}
        </div>
      )
    )
  }

  if (isError) {
    if (errorNode) return errorNode
    return (
      <div className="mt-8 text-red-600">
        {errorLabel}
        {onRetry ? (
          <button type="button" className="ml-2 underline" onClick={onRetry}>
            Retry
          </button>
        ) : (
          ' Reload the page.'
        )}
      </div>
    )
  }

  return <>{children}</>
}
