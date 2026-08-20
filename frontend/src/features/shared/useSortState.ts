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
 * server-sorted tables alike. Column and direction live in ONE state object
 * rather than two: with separate `useState` calls, picking a new column
 * queues two updates, and a consumer whose query key is derived from both
 * would fetch once against the new column paired with the old direction.
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
