/**
 * One kanban card.
 *
 * DOM CONTRACT — the first <span> in this card is the `#job_number` badge.
 * Two E2E specs read the job number with `card.locator('span').first()`, so
 * nothing rendered above the badge may be a span (use div/svg). The badge is
 * the first child of the first row for exactly that reason.
 *
 * The card carries both `data-job-id` and `data-id`: v1 emitted both and the
 * ported specs use `data-job-id`, while `data-id` is what the drag tooling
 * and any hand-written selector reached for.
 */
import { DollarSign, Receipt, Settings2, XCircle } from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import type { KanbanJobOut } from '@/api'
import { formatDate, localIsoDate } from '@/lib/format'

import { StaffAvatar } from './StaffAvatar'
import { useJobCardDrag } from './useKanbanDrag'

/** Matches the type StaffPanel writes on dragstart. */
export const STAFF_DRAG_TYPE = 'application/x-drag-type'

interface JobCardProps {
  job: KanbanJobOut
  movePendingRef: React.RefObject<boolean>
  onAssignStaff: (jobId: string, staffId: string) => void
  /** The staff id armed by StaffPanel's mobile Assign button, or null when idle. */
  armedStaffId: string | null
  /** Tap-assign target (mobile, below lg): assigns armedStaffId instead of navigating. */
  onTapAssign: (jobId: string) => void
  /** Opens the status drawer (mobile, below lg) for this job. */
  onStatusChange: (job: KanbanJobOut) => void
}

function dueDateColor(deliveryDate: string): string {
  const today = localIsoDate()
  if (deliveryDate < today) return 'text-red-600'
  if (deliveryDate === today) return 'text-amber-600'
  return 'text-gray-900'
}

export function JobCard({
  job,
  movePendingRef,
  onAssignStaff,
  armedStaffId,
  onTapAssign,
  onStatusChange,
}: JobCardProps) {
  const navigate = useNavigate()
  const { ref, isDragging, shouldSuppressClick } = useJobCardDrag(
    job.id,
    job.status_key,
    movePendingRef,
  )
  const [isStaffDragOver, setIsStaffDragOver] = useState(false)

  // A finished job's delivery date is history, not a deadline (v1 JobCard.vue:376).
  const showDueDate =
    job.delivery_date !== null &&
    job.status_key !== 'recently_completed' &&
    job.status_key !== 'archived'
  const description = job.description?.trim()
  const hasStatusIcons = job.is_urgent || job.fully_invoiced || job.paid || job.rejected_flag

  // Native HTML5 handlers, gated on the staff transfer type: a card drag is a
  // pragmatic drag and must fall through to it untouched.
  const isStaffDrag = (event: React.DragEvent<HTMLDivElement>) =>
    event.dataTransfer.types.includes(STAFF_DRAG_TYPE)

  return (
    <div
      ref={ref}
      className={`job-card relative flex cursor-grab flex-col overflow-hidden rounded-lg border bg-white p-3 shadow-sm transition-colors active:cursor-grabbing ${
        isStaffDragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-200'
      } ${isDragging ? 'opacity-60' : ''}`}
      data-id={job.id}
      data-job-id={job.id}
      onClick={() => {
        // The tail of a drag is not a click on the card, even when the
        // pointer never left it.
        if (shouldSuppressClick()) return
        // Tap-assign armed (mobile, below lg): the tap assigns instead of
        // navigating (v1 JobCard.vue:361-368).
        if (armedStaffId) {
          onTapAssign(job.id)
          return
        }
        void navigate({ to: '/jobs/$jobId', params: { jobId: job.id } })
      }}
      onDragEnter={(event) => {
        if (!isStaffDrag(event)) return
        event.preventDefault()
        setIsStaffDragOver(true)
      }}
      onDragOver={(event) => {
        if (!isStaffDrag(event)) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
      }}
      onDragLeave={(event) => {
        if (!isStaffDrag(event)) return
        setIsStaffDragOver(false)
      }}
      onDrop={(event) => {
        if (!isStaffDrag(event)) return
        event.preventDefault()
        event.stopPropagation()
        setIsStaffDragOver(false)
        const staffId = event.dataTransfer.getData('text/plain')
        if (staffId) onAssignStaff(job.id, staffId)
      }}
    >
      {armedStaffId && (
        <div className="absolute inset-x-0 top-0 z-10 rounded-t-lg bg-blue-600/90 py-1 text-center text-[0.7rem] font-semibold text-white lg:hidden">
          Tap to assign
        </div>
      )}

      <div className="mb-1 flex items-center justify-between gap-2">
        <span
          className={`inline-flex items-center rounded-md px-2 py-1 text-[0.82rem] font-semibold tracking-wide text-white tabular-nums ${
            job.over_budget ? 'bg-red-600' : 'bg-blue-600'
          }`}
        >
          #{job.job_number}
        </span>

        <div className="flex items-center gap-1">
          <div
            className={`flex min-h-5 items-center gap-1 rounded p-1 ${
              job.people.length === 0 ? 'border border-dashed border-gray-300 bg-gray-50' : ''
            }`}
          >
            {job.people.map((person) => (
              <StaffAvatar key={person.id} person={person} size="small" />
            ))}
            {job.people.length === 0 && <div className="px-1 text-[10px] text-gray-400">+</div>}
          </div>

          {/* Mobile-only: opens the status drawer for this job. */}
          <button
            type="button"
            aria-label="Change job status"
            title="Change job status"
            className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-gray-200 bg-white/90 text-gray-500 shadow-sm lg:hidden"
            onClick={(event) => {
              event.stopPropagation()
              onStatusChange(job)
            }}
          >
            <Settings2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <h4 className="mb-1 text-[0.98rem] leading-tight font-semibold text-gray-900">
        {job.company_name}
      </h4>

      <p
        className={`mb-2 text-[0.84rem] leading-snug whitespace-pre-wrap text-gray-700 ${
          description ? 'line-clamp-2' : 'line-clamp-1'
        }`}
      >
        {description ? description : job.name}
      </p>

      {job.person_name && (
        <div className="truncate text-[0.8rem] font-medium text-gray-600">
          <span className="font-semibold">Person:</span> {job.person_name}
        </div>
      )}

      {showDueDate && job.delivery_date !== null && (
        <div className={`truncate text-[0.8rem] font-bold ${dueDateColor(job.delivery_date)}`}>
          Due: {formatDate(job.delivery_date)}
        </div>
      )}

      {hasStatusIcons && (
        <div className="absolute right-1.5 bottom-1.5 flex items-center gap-1">
          {job.is_urgent && (
            <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-600">
              URGENT
            </span>
          )}
          {job.fully_invoiced && (
            <Receipt className="h-4 w-4 text-green-600" aria-label="Fully invoiced" />
          )}
          {job.paid && <DollarSign className="h-4 w-4 text-green-600" aria-label="Paid" />}
          {job.rejected_flag && <XCircle className="h-4 w-4 text-red-500" aria-label="Rejected" />}
        </div>
      )}
    </div>
  )
}
