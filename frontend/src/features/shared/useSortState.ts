import { useCallback, useState } from 'react'

export type SortDir = 'asc' | 'desc'

export interface SortState<TColumn extends string> {
  sortBy: TColumn
  sortDir: SortDir
  /** Re-sorts: a new column starts ascending, the current column flips. */
  onSort: (column: TColumn) => void
}

/**
 * The one owner of click-a-header-to-sort state, for client- and
 * server-sorted tables alike.
 *
 * Opus: column and direction live in ONE state object because they are one
 * fact — a sort — and splitting them lets a caller read or pass half of it.
 * Not for the reason first recorded here: that claimed two `useState` calls
 * would let a derived query key fetch the new column against the old
 * direction, which React 19's batching makes impossible.
 */
export function useSortState<TColumn extends string>(
  initialColumn: TColumn,
  initialDir: SortDir = 'asc',
): SortState<TColumn> {
  const [state, setState] = useState<{ sortBy: TColumn; sortDir: SortDir }>({
    sortBy: initialColumn,
    sortDir: initialDir,
  })

  const onSort = useCallback((column: TColumn) => {
    setState((current) =>
      current.sortBy === column
        ? { sortBy: column, sortDir: current.sortDir === 'asc' ? 'desc' : 'asc' }
        : { sortBy: column, sortDir: 'asc' },
    )
  }, [])

  return { sortBy: state.sortBy, sortDir: state.sortDir, onSort }
}
