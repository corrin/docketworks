import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type { JobForPurchasing } from '@/api'

// A PO line never books against a closed job (v1 rule).
const EXCLUDED_STATUSES = new Set(['rejected', 'archived', 'completed'])

interface JobSelectProps {
  /** The bound job's display facts, from the line (or draft) this cell edits. */
  jobNumber: number | null
  jobName: string | null
  jobs: readonly JobForPurchasing[]
  jobsLoading: boolean
  disabled?: boolean
  onPickJob: (job: JobForPurchasing) => void
}

export function jobSelectLabel(jobNumber: number | null, jobName: string | null): string {
  if (jobNumber === null) return ''
  return jobName === null || jobName === '' ? String(jobNumber) : `${jobNumber} - ${jobName}`
}

export function filterJobs(jobs: readonly JobForPurchasing[], term: string): JobForPurchasing[] {
  const available = jobs.filter((job) => !EXCLUDED_STATUSES.has(job.status.toLowerCase()))
  const lowered = term.trim().toLowerCase()
  if (lowered === '') return available
  return available.filter(
    (job) =>
      String(job.job_number).includes(lowered) ||
      job.name.toLowerCase().includes(lowered) ||
      job.company_name.toLowerCase().includes(lowered) ||
      job.job_display_name.toLowerCase().includes(lowered),
  )
}

/**
 * Inline job picker for PO lines: a plain input whose VALUE renders the
 * selection (`{number} - {name}`), with a filtering dropdown underneath.
 * Rejected alternative: TimesheetJobPicker — a button-trigger popover that
 * clears its search after selection, so the selection would never render
 * back into an input (the wire contract here reads the input's value).
 *
 * The dropdown is portalled to body with fixed positioning: the grid lives
 * in an overflow-x-auto container, which would clip an absolutely
 * positioned dropdown.
 */
export function JobSelect({
  jobNumber,
  jobName,
  jobs,
  jobsLoading,
  disabled = false,
  onPickJob,
}: JobSelectProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [editing, setEditing] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [position, setPosition] = useState({ top: 0, left: 0, width: 0 })

  const value = editing ? searchTerm : jobSelectLabel(jobNumber, jobName)
  const filtered = filterJobs(jobs, editing ? searchTerm : '')

  // Unmounting mid-blur-grace-period must not fire a state update on a
  // gone component.
  useEffect(
    () => () => {
      if (blurTimer.current !== null) clearTimeout(blurTimer.current)
    },
    [],
  )

  const reposition = () => {
    const input = inputRef.current
    if (!input) return
    const rect = input.getBoundingClientRect()
    setPosition({ top: rect.bottom + 4, left: rect.left, width: rect.width })
  }

  const select = (job: JobForPurchasing) => {
    setEditing(false)
    setSearchTerm('')
    setOpen(false)
    setActiveIndex(-1)
    onPickJob(job)
    inputRef.current?.blur()
  }

  // Closing without a pick must not leave the input showing an abandoned
  // search term — it would then read as bound to nothing, and the next
  // focus would filter against stale text instead of the real selection.
  const closeWithoutSelecting = () => {
    setEditing(false)
    setSearchTerm('')
    setOpen(false)
    setActiveIndex(-1)
  }

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="text"
        value={value}
        disabled={disabled}
        placeholder="Assign job..."
        autoComplete="off"
        data-automation-id="JobSelect-job-search"
        role="combobox"
        aria-expanded={open}
        aria-controls="JobSelect-dropdown"
        aria-activedescendant={
          open && activeIndex >= 0
            ? `JobSelect-option-${filtered[activeIndex]?.job_number}`
            : undefined
        }
        className="w-40 rounded border border-slate-200 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-50"
        onFocus={() => {
          reposition()
          setOpen(true)
        }}
        // The 150ms grace period lets an option's mousedown land before the
        // dropdown unmounts; closing on blur alone loses the click.
        onBlur={() => {
          blurTimer.current = setTimeout(closeWithoutSelecting, 150)
        }}
        onChange={(event) => {
          setEditing(true)
          setSearchTerm(event.target.value)
          setActiveIndex(-1)
          reposition()
          setOpen(true)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            closeWithoutSelecting()
            inputRef.current?.blur()
            return
          }
          if (!open || filtered.length === 0) return
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            setActiveIndex((current) => (current + 1) % filtered.length)
          } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            setActiveIndex((current) => (current - 1 + filtered.length) % filtered.length)
          } else if (event.key === 'Enter' && activeIndex >= 0) {
            event.preventDefault()
            const job = filtered[activeIndex]
            if (job) select(job)
          }
        }}
      />
      {open &&
        !disabled &&
        createPortal(
          <div
            id="JobSelect-dropdown"
            data-automation-id="JobSelect-dropdown"
            role="listbox"
            style={{ top: position.top, left: position.left, width: position.width }}
            className="fixed z-50 max-h-60 overflow-y-auto rounded-md border border-gray-300 bg-white shadow-lg"
          >
            {filtered.map((job, index) => (
              <div
                key={job.id}
                id={`JobSelect-option-${job.job_number}`}
                data-automation-id={`JobSelect-option-${job.job_number}`}
                role="option"
                aria-selected={index === activeIndex}
                className={`cursor-pointer border-b border-gray-100 px-3 py-2 last:border-b-0 hover:bg-blue-50 ${
                  index === activeIndex ? 'bg-blue-50' : ''
                }`}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => {
                  event.preventDefault()
                  select(job)
                }}
              >
                <div className="font-medium text-gray-900">{job.job_number}</div>
                <div className="truncate text-sm text-gray-600">{job.name}</div>
                {job.company_name && (
                  <div className="truncate text-xs text-gray-500">Company: {job.company_name}</div>
                )}
              </div>
            ))}
            {jobsLoading && (
              <div className="px-3 py-2 text-sm text-gray-500">Jobs are loading, please wait</div>
            )}
            {!jobsLoading && filtered.length === 0 && (
              <div className="px-3 py-2 text-sm text-gray-500">
                {editing && searchTerm.trim() !== ''
                  ? `No jobs found for "${searchTerm}"`
                  : 'No jobs available'}
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  )
}
