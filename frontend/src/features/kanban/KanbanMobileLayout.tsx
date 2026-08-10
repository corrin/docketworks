/**
 * The office board below `lg`: a sticky toolbar (native `<select>` + a
 * horizontally-scrolling pill row) above a horizontal scroll-snap strip, one
 * panel per column. ALL columns stay mounted — the toolbar scrolls the
 * target column into view, it does not filter (v1 KanbanMobileLayout.vue).
 * An unmounted column would break the post-drawer assertion
 * `[data-kanban-status="X"] [data-job-id="Y"]`.
 *
 * The page scrolls vertically (KanbanColumn's job list is natural-height
 * below lg, see KanbanColumn.tsx) and this strip scrolls horizontally — two
 * independent scroll axes, matching v1's mobile layout rather than v1's
 * desktop 90vh-internal-scroll column.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import type { KanbanJobOut } from '@/api'

import { KanbanColumn } from './KanbanColumn'
import type { KanbanColumnView } from './useKanbanBoard'

interface KanbanMobileLayoutProps {
  columns: KanbanColumnView[]
  isSearchActive: boolean
  movePendingRef: React.RefObject<boolean>
  dragOverStatus: string | null
  setColumnDragOver: (statusKey: string, isOver: boolean) => void
  onAssignStaff: (jobId: string, staffId: string) => void
  armedStaffId: string | null
  onTapAssign: (jobId: string) => void
  onStatusChange: (job: KanbanJobOut) => void
}

export function KanbanMobileLayout({
  columns,
  isSearchActive,
  movePendingRef,
  dragOverStatus,
  setColumnDragOver,
  onAssignStaff,
  armedStaffId,
  onTapAssign,
  onStatusChange,
}: KanbanMobileLayoutProps) {
  const firstColumn = columns[0]
  if (!firstColumn) {
    throw new Error('Kanban mobile layout requires at least one column')
  }

  const [selectedStatus, setSelectedStatus] = useState<string>(firstColumn.id)
  const scrollerRef = useRef<HTMLDivElement | null>(null)
  const panelRefs = useRef(new Map<string, HTMLDivElement>())

  const scrollColumnIntoView = useCallback((statusKey: string) => {
    const container = scrollerRef.current
    const panel = panelRefs.current.get(statusKey)
    if (!container || !panel) return
    const target = panel.offsetLeft - (container.clientWidth - panel.clientWidth) / 2
    container.scrollTo({ left: Math.max(0, target), behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollColumnIntoView(selectedStatus)
  }, [selectedStatus, scrollColumnIntoView])

  const selectStatus = (statusKey: string) => {
    setSelectedStatus(statusKey)
  }

  return (
    <div className="space-y-3">
      <div className="sticky top-0 z-30 space-y-2 rounded-2xl border border-gray-200 bg-white/95 p-3 shadow-sm backdrop-blur">
        <select
          value={selectedStatus}
          onChange={(event) => selectStatus(event.target.value)}
          className="w-full rounded-lg border border-gray-300 bg-white p-2.5 text-sm font-medium text-gray-900 focus:border-transparent focus:ring-2 focus:ring-blue-500"
        >
          {columns.map((column) => (
            <option key={column.id} value={column.id}>
              {column.label} ({column.countDisplay})
            </option>
          ))}
        </select>

        <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {columns.map((column) => (
            <button
              key={column.id}
              type="button"
              onClick={() => selectStatus(column.id)}
              className={`mobile-status-pill inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-2 text-xs whitespace-nowrap transition-all ${
                column.id === selectedStatus
                  ? 'mobile-status-pill--active border-blue-700 bg-blue-700 text-white'
                  : 'border-blue-300 bg-white text-blue-700'
              }`}
            >
              <span className="truncate">{column.label}</span>
              <span className="font-bold opacity-85">{column.countDisplay}</span>
            </button>
          ))}
        </div>
      </div>

      <div
        ref={scrollerRef}
        className="flex gap-4 overflow-x-auto px-1 pt-2 pb-6 [-ms-overflow-style:none] [scroll-snap-type:x_mandatory] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {columns.map((column) => (
          <div
            key={column.id}
            ref={(element) => {
              if (element) {
                panelRefs.current.set(column.id, element)
              } else {
                panelRefs.current.delete(column.id)
              }
            }}
            className="w-[calc(100vw-3rem)] max-w-[420px] shrink-0 [scroll-snap-align:center]"
          >
            <KanbanColumn
              column={column}
              isDragOver={dragOverStatus === column.id}
              isSearchActive={isSearchActive}
              movePendingRef={movePendingRef}
              setColumnDragOver={setColumnDragOver}
              onAssignStaff={onAssignStaff}
              armedStaffId={armedStaffId}
              onTapAssign={onTapAssign}
              onStatusChange={onStatusChange}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
