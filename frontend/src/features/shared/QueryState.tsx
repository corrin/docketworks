import type { ReactNode } from 'react'

interface QueryStateProps {
  isPending: boolean
  isError: boolean
  /** Omit for a static "Reload the page." message; pass the query's
      refetch for a working Retry button. */
  onRetry?: () => void
  loadingLabel: string
  /** The loading element's data-automation-id — must unmount (not just
      hide) once loaded, since an E2E wait on it can require leaving the
      tree. Only supply where a spec asserts one. */
  loadingAutomationId?: string
  errorLabel: string
  /** Rendered only once neither pending nor errored. */
  children: ReactNode
}

/**
 * The one owner of the pending/error gate every query-backed page or panel
 * repeats at its top: loading text, then error text with either a working
 * Retry or a static "Reload the page." — reused standalone (a detail page,
 * a card, a grid) and internally by `ListTable` (`features/shared/
 * ListTable.tsx`) for its rows-table cousin.
 */
export function QueryState({
  isPending,
  isError,
  onRetry,
  loadingLabel,
  loadingAutomationId,
  errorLabel,
  children,
}: QueryStateProps) {
  if (isPending) {
    return (
      <div data-automation-id={loadingAutomationId} className="mt-8 text-gray-500">
        {loadingLabel}
      </div>
    )
  }

  if (isError) {
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
