/**
 * The office kanban board: staff strip above, then a desktop grid (one equal
 * column per OFFICE_COLUMN_IDS entry) at `lg` and above, or KanbanMobileLayout's scroll-snap strip
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
import { useCallback, useRef, useState } from 'react'

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
  // Trimmed once, here, for every consumer.
  const searchTerm = searchQuery.trim()
  // Both pauses the reconciliation loop reads are owned here: the drag
  // monitor sets "a drag is in flight" and the board hook sets "a move is
  // persisting", and only this component sees both. Owning the refs is what
  // lets reconcile() exist before the hooks that trigger it, so each hook
  // takes it as a plain callback instead of a ref filled in afterwards.
  const isDraggingRef = useRef(false)
  const movePendingRef = useRef(false)
  const { reconcile } = useKanbanReconciliation({ isDraggingRef, movePendingRef, searchTerm })

  // On drag release — moveJob settling, or a drag that ends with no move to
  // settle — fire reconcile() once instead of leaving a deferred tick to
  // wait out the rest of the 30s interval. reconcile() re-checks the pause
  // itself, so a call landing while still paused is a safe no-op.
  const board = useKanbanBoard(searchTerm, { movePendingRef, onMoveSettled: reconcile })
  const { dragOverStatus, setColumnDragOver } = useKanbanDragMonitor(
    board.moveJob,
    reconcile,
    isDraggingRef,
  )
  const { staff, isStaffLoading, isStaffError, assignStaff } = useStaffAssignment(searchTerm)
  const isDesktop = useMediaQuery(DESKTOP_MEDIA_QUERY)

  const [statusDrawerJob, setStatusDrawerJob] = useState<KanbanJobOut | null>(null)
  // Tap-assign is a mobile concept (v1 kanban.vue watch(isDesktop, ...)): a
  // selection armed on mobile must not come back armed after a trip through
  // the desktop layout, where nothing shows it. The selection carries the
  // layout it was armed under and is cleared during the first render under
  // the other one — React's adjust-state-on-prop-change shape, not an effect,
  // so nothing ever reads the stale value.
  const [armed, setArmed] = useState<{ staffId: string | null; isDesktop: boolean }>({
    staffId: null,
    isDesktop,
  })
  if (armed.isDesktop !== isDesktop) setArmed({ staffId: null, isDesktop })
  const armedStaffId = isDesktop || armed.isDesktop !== isDesktop ? null : armed.staffId

  const handleToggleTapAssign = useCallback((staffId: string) => {
    setArmed((current) => ({
      staffId: current.staffId === staffId ? null : staffId,
      isDesktop: current.isDesktop,
    }))
  }, [])

  const handleTapAssign = useCallback(
    async (jobId: string) => {
      if (!armedStaffId) return
      const staffId = armedStaffId
      const success = await assignStaff(jobId, staffId)
      if (success) setArmed((current) => ({ ...current, staffId: null }))
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
            isError={isStaffError}
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
              movePendingRef={movePendingRef}
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
          movePendingRef={movePendingRef}
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
