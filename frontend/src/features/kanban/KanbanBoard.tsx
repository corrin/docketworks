/**
 * The office kanban board: staff strip above, then a desktop grid (six equal
 * columns) at `lg` and above, or KanbanMobileLayout's scroll-snap strip
 * below it. Layout is a real conditional render, not a CSS-only toggle: a
 * resize across the breakpoint unmounts one and mounts the other, which is
 * exactly the "stale sortable after layout switch" scenario
 * debug-drag-bugs.spec.ts guards (task-4-brief) — pragmatic's drag
 * registrations must survive that teardown/remount cleanly.
 *
 * SEAM: `sessionStorage.boardMode` is v1's office/workshop switch. It is
 * deliberately NOT read here yet — with workshop mode deferred there is one
 * board, and a read whose result is discarded reads as a bug. The workshop
 * slice adds the branch (WorkshopKanbanView renders the same column
 * component over a different column set), and every value including an
 * absent key means "office" until then.
 */
import { useCallback, useEffect, useState } from 'react'

import type { KanbanJobOut } from '@/api'
import { DESKTOP_MEDIA_QUERY, useMediaQuery } from '@/lib/useMediaQuery'

import { OFFICE_COLUMN_IDS } from './columns'
import { KanbanColumn } from './KanbanColumn'
import { KanbanMobileLayout } from './KanbanMobileLayout'
import { StaffPanel } from './StaffPanel'
import { StatusDrawer } from './StatusDrawer'
import { useKanbanBoard } from './useKanbanBoard'
import { useKanbanDragMonitor } from './useKanbanDrag'
import { useKanbanReconciliation } from './useKanbanReconciliation'
import { useStaffAssignment } from './useStaffAssignment'

interface KanbanBoardProps {
  /** The `q` search param; '' when the board is unfiltered. */
  searchQuery: string
}

export function KanbanBoard({ searchQuery }: KanbanBoardProps) {
  const board = useKanbanBoard(searchQuery)
  const { dragOverStatus, setColumnDragOver, isDraggingRef } = useKanbanDragMonitor(board.moveJob)
  const { staff, isStaffLoading, assignStaff } = useStaffAssignment(board.searchTerm)
  const isDesktop = useMediaQuery(DESKTOP_MEDIA_QUERY)

  // Composed here rather than inside useKanbanBoard: the loop pauses on both
  // "a drag is in flight" and "a move is persisting", and only one component
  // sees both — the drag monitor is created from board.moveJob, so the board
  // hook cannot reach it without a circular dependency.
  useKanbanReconciliation({
    isDraggingRef,
    movePendingRef: board.movePendingRef,
    searchTerm: board.searchTerm,
  })

  const [statusDrawerJob, setStatusDrawerJob] = useState<KanbanJobOut | null>(null)
  const [armedStaffId, setArmedStaffId] = useState<string | null>(null)

  // Tap-assign is a mobile concept (v1 kanban.vue watch(isDesktop, ...)): an
  // armed selection surviving a resize to desktop would leave the next card
  // click assigning instead of navigating, with no armed-state UI visible to
  // explain why.
  useEffect(() => {
    if (isDesktop) setArmedStaffId(null)
  }, [isDesktop])

  const handleToggleTapAssign = useCallback((staffId: string) => {
    setArmedStaffId((current) => (current === staffId ? null : staffId))
  }, [])

  const handleTapAssign = useCallback(
    async (jobId: string) => {
      if (!armedStaffId) return
      const staffId = armedStaffId
      const success = await assignStaff(jobId, staffId)
      if (success) setArmedStaffId(null)
    },
    [armedStaffId, assignStaff],
  )

  return (
    <main data-automation-id="kanban-page" className="flex flex-col p-3 sm:p-4 lg:p-6">
      <div className="mb-2 flex justify-center px-2 md:mb-3">
        <div className="w-full max-w-6xl">
          <StaffPanel
            staff={staff}
            isLoading={isStaffLoading}
            activeStaffIds={board.activeStaffIds}
            onToggleFilter={board.toggleStaffFilter}
            armedStaffId={armedStaffId}
            onToggleTapAssign={handleToggleTapAssign}
          />
        </div>
      </div>

      {isDesktop ? (
        <div
          className="grid gap-2 xl:gap-3"
          style={{ gridTemplateColumns: `repeat(${OFFICE_COLUMN_IDS.length}, minmax(0, 1fr))` }}
        >
          {board.columns.map((column) => (
            <KanbanColumn
              key={column.id}
              column={column}
              isDragOver={dragOverStatus === column.id}
              isSearchActive={board.isSearchActive}
              movePendingRef={board.movePendingRef}
              setColumnDragOver={setColumnDragOver}
              onAssignStaff={assignStaff}
              armedStaffId={armedStaffId}
              onTapAssign={handleTapAssign}
              onStatusChange={setStatusDrawerJob}
            />
          ))}
        </div>
      ) : (
        <KanbanMobileLayout
          columns={board.columns}
          isSearchActive={board.isSearchActive}
          movePendingRef={board.movePendingRef}
          dragOverStatus={dragOverStatus}
          setColumnDragOver={setColumnDragOver}
          onAssignStaff={assignStaff}
          armedStaffId={armedStaffId}
          onTapAssign={handleTapAssign}
          onStatusChange={setStatusDrawerJob}
        />
      )}

      <StatusDrawer
        job={statusDrawerJob}
        statusOptions={board.statusOptions}
        onUpdateStatus={board.updateStatus}
        onClose={() => setStatusDrawerJob(null)}
      />
    </main>
  )
}
