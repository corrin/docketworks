/**
 * One board column: a header, then the scrolling card list.
 *
 * DOM CONTRACT — `data-status` belongs on the scrolling LIST element, not on
 * the outer card-panel wrapper (v1 KanbanColumn.vue:19). It is simultaneously
 * the drop target and the selector the specs locate cards under
 * (`[data-status="draft"] [data-job-id]`), and the two must be the same
 * element or a drop can land somewhere the assertions cannot see.
 */
import type { KanbanJobOut } from '@/api'

import { JobCard } from './JobCard'
import type { KanbanColumnView } from './useKanbanBoard'
import { useColumnDropTarget } from './useKanbanDrag'

interface KanbanColumnProps {
  column: KanbanColumnView
  isDragOver: boolean
  isSearchActive: boolean
  movePendingRef: React.RefObject<boolean>
  setColumnDragOver: (statusKey: string, isOver: boolean) => void
  onAssignStaff: (jobId: string, staffId: string) => void
}

export function KanbanColumn({
  column,
  isDragOver,
  isSearchActive,
  movePendingRef,
  setColumnDragOver,
  onAssignStaff,
}: KanbanColumnProps) {
  const lastJob: KanbanJobOut | undefined = column.jobs[column.jobs.length - 1]
  const listRef = useColumnDropTarget(column.id, lastJob?.id ?? null, setColumnDragOver)

  return (
    <div className="w-full shrink-0">
      <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 p-3">
          <h3 className="text-sm font-semibold text-gray-900">{column.label}</h3>
          <span className="text-sm font-bold text-gray-400" title={column.tooltip}>
            ({column.countDisplay})
          </span>
        </div>

        <div
          ref={listRef}
          data-status={column.id}
          className={`relative h-[calc(90vh-12.5rem)] space-y-3 overflow-y-auto p-3 transition-colors duration-200 ${
            isDragOver ? 'border-blue-200 bg-blue-50' : ''
          }`}
        >
          {column.jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              movePendingRef={movePendingRef}
              onAssignStaff={onAssignStaff}
            />
          ))}

          {column.jobs.length === 0 && !column.isLoading && (
            <div className="flex h-32 items-center justify-center text-center text-sm text-gray-500">
              {isSearchActive ? 'No matching jobs in ' : 'No jobs in '}
              {column.label.toLowerCase()}
            </div>
          )}

          {column.jobs.length === 0 && column.isLoading && (
            <div className="flex h-32 items-center justify-center text-center text-sm text-gray-500">
              Jobs in {column.label.toLowerCase()} status are still loading, please wait
            </div>
          )}

          {/* SEAM: a truncated column shows "X of Y" but offers no Load More.
              v1's button was a no-op TODO, so shipping an inert one would only
              promise something neither version does; paging arrives with the
              reconciliation slice that already owns column refresh. */}
        </div>
      </div>
    </div>
  )
}
