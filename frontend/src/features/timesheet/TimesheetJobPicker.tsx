import { useEffect, useMemo, useRef, useState } from 'react'

import type { TimesheetJobOut } from '@/api'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { rateForSubtype } from './labourRates'

const TYPED_SEARCH_LIMIT = 15

export interface TimesheetJobPickerProps {
  /** `SmartTimesheetTable-jobPicker-${rowIndex}` — every inner id derives from it. */
  automationIdPrefix: string
  jobs: readonly TimesheetJobOut[]
  selected: TimesheetJobOut | null
  disabled: boolean
  /** Rendered as data-entry-seq on the trigger (the keyboard spec binds rows by it). */
  entrySeq: number | null
  gridRow: number
  onSelect: (job: TimesheetJobOut) => void
}

function statusLabel(status: string | null | undefined): string {
  switch (status) {
    case 'draft':
      return 'Draft'
    case 'awaiting_approval':
      return 'Awaiting Approval'
    case 'approved':
      return 'Approved'
    case 'in_progress':
      return 'In Progress'
    case 'recently_completed':
      return 'Recently Completed'
    case 'archived':
      return 'Archived'
    case 'special':
      return 'Special'
    case 'on_hold':
      return 'On Hold'
    case 'unusual':
      return 'Unusual'
    default:
      return ''
  }
}

/** Workshop charge-out rate shown in the picker (rates are per labour subtype). */
function jobDisplayRate(job: TimesheetJobOut): number {
  return rateForSubtype(job.labour_rates, null)
}

/**
 * The timesheet job picker (v1 TimesheetJobPicker port). Not cmdk: the
 * keyboard contract is v1's — a maintained highlight index, Enter picking
 * the highlighted (or sole) match, and Tab picking the highlighted match so
 * the caller can move focus on — which fights cmdk's internal selection
 * model rather than reusing it.
 */
export function TimesheetJobPicker({
  automationIdPrefix,
  jobs,
  selected,
  disabled,
  entrySeq,
  gridRow,
  onSelect,
}: TimesheetJobPickerProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [highlighted, setHighlighted] = useState(-1)
  const searchRef = useRef<HTMLInputElement>(null)
  // Set while closing because of a pick: the caller moves focus (to the
  // hours cell), so Radix's default focus-restore-to-trigger must not run.
  // An Escape/outside close keeps the default restore.
  const pickedRef = useRef(false)

  const filtered = useMemo<TimesheetJobOut[]>(() => {
    const term = search.trim().toLowerCase()
    if (!term) {
      // Blank search shows the whole (workload-bounded) list, selected first.
      if (selected) {
        return [selected, ...jobs.filter((job) => job.id !== selected.id)]
      }
      return [...jobs]
    }
    return jobs
      .filter((job) => {
        const num = String(job.job_number).toLowerCase()
        const name = job.name.toLowerCase()
        const company = (job.company_name ?? '').toLowerCase()
        return num.includes(term) || name.includes(term) || company.includes(term)
      })
      .slice(0, TYPED_SEARCH_LIMIT)
  }, [jobs, search, selected])

  // The default highlight is the first match, reset when the TERM changes —
  // not when the filtered array's identity changes, because a parent
  // re-render rebuilds the jobs array and would clobber arrow-key state.
  const filteredCount = filtered.length
  useEffect(() => {
    if (!open) return
    setHighlighted(filteredCount > 0 ? 0 : -1)
  }, [open, search, filteredCount])

  useEffect(() => {
    if (!open) {
      setSearch('')
      setHighlighted(-1)
    }
  }, [open])

  const pick = (job: TimesheetJobOut) => {
    pickedRef.current = true
    onSelect(job)
    setOpen(false)
  }

  const onSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (filtered.length === 0) return
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        setHighlighted((current) => Math.min(current + 1, filtered.length - 1))
        break
      case 'ArrowUp':
        event.preventDefault()
        setHighlighted((current) => Math.max(current - 1, 0))
        break
      case 'Enter': {
        event.preventDefault()
        const target = filtered[highlighted] ?? (filtered.length === 1 ? filtered[0] : undefined)
        if (target) pick(target)
        break
      }
      case 'Tab': {
        // Tab commits the highlighted job and lets the caller's focus logic
        // take over (the grid moves focus to the hours cell after a pick).
        // The sole-match fallback covers a highlight reset racing a rapid
        // type-then-Tab under load — with one match there is no ambiguity.
        const target = filtered[highlighted] ?? (filtered.length === 1 ? filtered[0] : undefined)
        if (target) {
          event.preventDefault()
          pick(target)
        }
        break
      }
      case 'Escape':
        event.preventDefault()
        setOpen(false)
        break
      default:
        break
    }
  }

  const triggerLabel = selected ? `#${selected.job_number}` : 'Select job…'

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          title={triggerLabel}
          className={`block w-full max-w-[10ch] truncate rounded border border-transparent px-2 py-1 text-left text-sm hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-50 ${selected ? '' : 'text-slate-400'}`}
          data-automation-id={`${automationIdPrefix}-trigger`}
          data-entry-seq={entrySeq ?? undefined}
          data-grid-nav-cell="true"
          data-grid-row={gridRow}
          data-grid-col="jobNumber"
          onFocus={() => {
            // An empty enabled row opens straight into search — the create
            // flow's focus handoff lands here and must not need a click.
            if (!disabled && !selected) setOpen(true)
          }}
        >
          {triggerLabel}
          {selected?.is_urgent && (
            <span className="ml-1 inline-block rounded bg-red-50 px-1 text-[10px] font-bold text-red-600">
              !
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[360px] p-0"
        align="start"
        onOpenAutoFocus={(event) => {
          // Take over the focus trap so the search input gets focus.
          event.preventDefault()
          searchRef.current?.focus()
        }}
        onCloseAutoFocus={(event) => {
          if (pickedRef.current) {
            event.preventDefault()
            pickedRef.current = false
          }
        }}
      >
        <div className="border-b border-slate-200 p-2">
          <input
            ref={searchRef}
            value={search}
            placeholder="Search jobs… (job number, name, or company)"
            className="h-8 w-full rounded border border-slate-200 px-2 text-sm"
            data-automation-id={`${automationIdPrefix}-search`}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={onSearchKeyDown}
          />
        </div>
        <div
          className="max-h-[300px] overflow-y-auto"
          data-automation-id={`${automationIdPrefix}-list`}
        >
          {filtered.length === 0 && (
            <div className="px-3 py-2 text-sm italic text-slate-500">No jobs found</div>
          )}
          {filtered.map((job, index) => (
            <div
              key={job.id}
              className={`cursor-pointer border-b border-slate-100 px-3 py-2 text-sm last:border-b-0 ${index === highlighted ? 'bg-blue-50' : 'hover:bg-slate-50'}`}
              data-automation-id={`${automationIdPrefix}-option-${job.job_number}`}
              onMouseEnter={() => setHighlighted(index)}
              onClick={() => pick(job)}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="shrink-0 font-semibold text-slate-800">#{job.job_number}</span>
                <div className="flex items-center gap-1">
                  {job.is_urgent && (
                    <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-600">
                      URGENT
                    </span>
                  )}
                  {statusLabel(job.status) && (
                    <span className="text-right text-[11px] font-medium leading-tight text-slate-500">
                      {statusLabel(job.status)}
                    </span>
                  )}
                </div>
              </div>
              <div className="mt-0.5 break-words font-medium leading-tight text-slate-700">
                {job.name}
              </div>
              <div className="text-xs leading-tight text-slate-500">
                Company: {job.company_name ?? 'No Company'}
              </div>
              <div className="text-[11px] leading-tight text-slate-400">
                Rate: ${jobDisplayRate(job)}/hr
              </div>
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
