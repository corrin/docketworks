/**
 * The office kanban board: staff strip above, six equal columns below.
 *
 * SEAM: `sessionStorage.boardMode` is v1's office/workshop switch. It is
 * deliberately NOT read here yet — with workshop mode deferred there is one
 * board, and a read whose result is discarded reads as a bug. The workshop
 * slice adds the branch (WorkshopKanbanView renders the same column
 * component over a different column set), and every value including an
 * absent key means "office" until then.
 *
 * Mobile is a later slice: at small viewports these six columns overflow
 * horizontally rather than stacking, which is accepted for this PR.
 */
import { OFFICE_COLUMN_IDS } from './columns'
import { KanbanColumn } from './KanbanColumn'
import { StaffPanel } from './StaffPanel'
import { useKanbanBoard } from './useKanbanBoard'
import { useKanbanDragMonitor } from './useKanbanDrag'
import { useStaffAssignment } from './useStaffAssignment'

interface KanbanBoardProps {
  /** The `q` search param; '' when the board is unfiltered. */
  searchQuery: string
}

export function KanbanBoard({ searchQuery }: KanbanBoardProps) {
  const board = useKanbanBoard(searchQuery)
  const { dragOverStatus, setColumnDragOver } = useKanbanDragMonitor(board.moveJob)
  const { staff, isStaffLoading, assignStaff } = useStaffAssignment()

  return (
    <main data-automation-id="kanban-page" className="flex flex-col p-3 sm:p-4 lg:p-6">
      <div className="mb-2 flex justify-center px-2 md:mb-3">
        <div className="w-full max-w-6xl">
          <StaffPanel
            staff={staff}
            isLoading={isStaffLoading}
            activeStaffIds={board.activeStaffIds}
            onToggleFilter={board.toggleStaffFilter}
          />
        </div>
      </div>

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
          />
        ))}
      </div>
    </main>
  )
}
