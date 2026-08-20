import { ChevronDown, ChevronUp } from 'lucide-react'

import type { SortDir } from './useSortState'

interface SortHeaderProps<TColumn extends string> {
  column: TColumn
  label: string
  automationId: string
  sortBy: TColumn
  sortDir: SortDir
  align: 'left' | 'right'
  onSort: (column: TColumn) => void
}

/**
 * The one sortable column header. Generic over the caller's column union so
 * a page keeps its own compile-time column names — a `string` prop would let
 * a typo sort by a column that does not exist.
 *
 * The indicator renders only on the active column. v1's forecast table also
 * drew a neutral up-down glyph on every inactive header, which reads as
 * "sorted" at a glance across ten columns; the direction chevron alone says
 * the same thing without the noise.
 */
export function SortHeader<TColumn extends string>({
  column,
  label,
  automationId,
  sortBy,
  sortDir,
  align,
  onSort,
}: SortHeaderProps<TColumn>) {
  const active = sortBy === column
  return (
    <th
      scope="col"
      data-automation-id={automationId}
      aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className="p-0"
    >
      {/* The button fills the cell so a click anywhere on the header (which
          is what the E2E spec targets) lands on a keyboard-operable control. */}
      <button
        type="button"
        className={`w-full cursor-pointer px-3 py-2 select-none hover:text-gray-900 ${
          align === 'right' ? 'text-right' : 'text-left'
        }`}
        onClick={() => onSort(column)}
      >
        {label}
        {active &&
          (sortDir === 'asc' ? (
            <ChevronUp className="ml-1 inline h-3 w-3" />
          ) : (
            <ChevronDown className="ml-1 inline h-3 w-3" />
          ))}
      </button>
    </th>
  )
}
