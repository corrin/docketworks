/**
 * The staff strip above the board. Each chip is both a filter toggle (click)
 * and a drag source for assignment (native HTML5 dragstart onto a card).
 *
 * DOM CONTRACT — the chip class is `.staff-item` and it carries
 * `data-staff-id`; the desktop spec locates chips by that class and reads the
 * id off the chip itself.
 */
import type { KanbanStaffOut } from '@/api'

import { StaffAvatar } from './StaffAvatar'
import { STAFF_DRAG_TYPE } from './JobCard'

interface StaffPanelProps {
  staff: KanbanStaffOut[]
  isLoading: boolean
  activeStaffIds: string[]
  onToggleFilter: (staffId: string) => void
}

export function StaffPanel({ staff, isLoading, activeStaffIds, onToggleFilter }: StaffPanelProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-4 text-sm text-gray-600">
        Loading staff members...
      </div>
    )
  }

  return (
    <div className="mb-2 flex justify-center px-2">
      <div className="flex max-w-full flex-wrap justify-center gap-2">
        {staff.map((member) => {
          const isActive = activeStaffIds.includes(member.id)
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
            </div>
          )
        })}
      </div>

      {/* SEAM: the mobile Assign/Selected buttons (v1's tap-to-assign) land
          with the mobile slice; on desktop the chip's drag is the whole
          interaction. */}
    </div>
  )
}
