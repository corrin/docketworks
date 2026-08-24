/**
 * The staff strip above the board. Each chip is both a filter toggle (click)
 * and a drag source for assignment (native HTML5 dragstart onto a card).
 * Below lg it also carries an Assign/Selected button (v1 StaffPanel.vue's
 * `enableMobileQuickAssign` branch) that arms tap-assign — dragging a chip
 * onto a card doesn't work on touch, so mobile gets a tap-tap flow instead.
 *
 * DOM CONTRACT — the chip class is `.staff-item` and it carries
 * `data-staff-id`; the desktop spec locates chips by that class and reads the
 * id off the chip itself. The Assign button is a real `<button>` named
 * "Assign" / "Selected" (kanban-mobile.spec.ts:
 * `getByRole('button', { name: /Assign|Selected/ })`).
 */
import type { KanbanStaffOut } from '@/api'

import { StaffAvatar } from '@/features/shared/StaffAvatar'
import { STAFF_DRAG_TYPE } from './JobCard'

interface StaffPanelProps {
  staff: KanbanStaffOut[]
  isLoading: boolean
  activeStaffIds: string[]
  onToggleFilter: (staffId: string) => void
  /** The staff id currently armed for tap-assign, or null when idle. */
  armedStaffId: string | null
  onToggleTapAssign: (staffId: string) => void
}

export function StaffPanel({
  staff,
  isLoading,
  activeStaffIds,
  onToggleFilter,
  armedStaffId,
  onToggleTapAssign,
}: StaffPanelProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-4 text-sm text-gray-600">
        Loading staff members...
      </div>
    )
  }

  const armedStaffName = staff.find((member) => member.id === armedStaffId)?.display_name

  return (
    <div className="mb-2 flex flex-col items-center gap-2 px-2">
      <div className="text-xs text-gray-600 lg:hidden">
        {armedStaffId ? (
          <span className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1 text-blue-900">
            Assigning to {armedStaffName}
            <button
              type="button"
              className="font-semibold text-blue-600 hover:text-blue-800"
              onClick={() => onToggleTapAssign(armedStaffId)}
            >
              Clear
            </button>
          </span>
        ) : (
          <span>
            <span className="font-semibold text-gray-900">Quick assign:</span> tap{' '}
            <span className="font-semibold">Assign</span> on a teammate, then tap a job card.
          </span>
        )}
      </div>

      <div className="flex max-w-full flex-wrap justify-center gap-2">
        {staff.map((member) => {
          const isActive = activeStaffIds.includes(member.id)
          const isArmed = armedStaffId === member.id
          return (
            <div
              key={member.id}
              className={`staff-item relative flex cursor-grab flex-col items-center transition-transform select-none hover:scale-105 active:scale-95 ${
                isActive ? 'scale-105 rounded-lg ring-2 ring-blue-400 ring-offset-1' : ''
              }`}
              data-staff-id={member.id}
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData(STAFF_DRAG_TYPE, 'staff')
                event.dataTransfer.setData('text/plain', member.id)
                event.dataTransfer.effectAllowed = 'copy'
              }}
              onClick={() => onToggleFilter(member.id)}
            >
              {/* pointer-events-none on the children so the drag always starts
                  from the chip, never from the image inside it. */}
              <div className="pointer-events-none mb-1">
                <StaffAvatar person={member} isActive={isActive} />
              </div>
              <span className="pointer-events-none max-w-[60px] truncate text-center text-xs text-gray-600">
                {member.display_name.split(' ')[0]}
              </span>
              <button
                type="button"
                className={`mt-1 rounded-full border px-2 py-0.5 text-[0.65rem] font-semibold lg:hidden ${
                  isArmed
                    ? 'border-blue-700 bg-blue-700 text-white'
                    : 'border-blue-300 bg-blue-50 text-blue-700'
                }`}
                onClick={(event) => {
                  event.stopPropagation()
                  onToggleTapAssign(member.id)
                }}
              >
                {isArmed ? 'Selected' : 'Assign'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
