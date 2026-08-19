import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useDebouncedValue } from './useDebouncedValue'

const SEARCH_DEBOUNCE_MS = 300
// Opus: Mirrors apps/job/services/job_search.MIN_SEARCH_TERM_LENGTH: below this a
// substring match is not selective enough to be worth a round trip, and the
// endpoint refuses it with a 400.
const MIN_SEARCH_TERM_LENGTH = 3

const NO_BACKGROUND_JOBS: readonly never[] = []

/**
 * The only job facts the picker itself searches and renders. Consumers pass
 * their own wire type (JobForPurchasing, TimesheetJobOut, …), which satisfies
 * this structurally, and `onSelect` hands that type straight back — the
 * timesheet's applyJobPick reads is_urgent and labour_rates off the picked
 * job, which a narrowed option type would discard.
 *
 * Opus: Rejected alternative: unifying the three backend job-option schemas into
 * one. The duplicated concept is the PICKER, not the payload — labour_rates
 * prices a cost line and is_stock_holding marks the stock job, neither of
 * which any picker draws — and a union payload would push /timesheets/jobs/,
 * already the fattest of the three, toward the E2E 100KB wire-size guard.
 */
export interface JobPickerOption {
  id: string
  job_number: number
  name: string
  company_name: string | null
  status: string
}

/** What the picker needs back from a screen's background search. Opus: Deliberately
    not TanStack's UseQueryResult: the picker uses three fields, and naming them
    keeps a caller free to satisfy this without a query at all. */
export interface BackgroundJobSearch<T extends JobPickerOption> {
  jobs: readonly T[]
  isFetching: boolean
  isError: boolean
}

export interface JobPickerProps<T extends JobPickerOption> {
  /** Every inner id derives from it: -trigger, -search, -list, -option-{job_number}. */
  automationIdPrefix: string
  ariaLabel: string
  /** Already reduced to what this screen may book against — the picker applies
      no eligibility rule of its own. */
  jobs: readonly T[]
  selected: T | null
  disabled: boolean
  loading: boolean
  placeholder: string
  /** The trigger's text. Takes the resolved job or null, because a row can be
      bound to a job the list no longer offers (archived, closed) and must
      still show what it holds. Returning '' means unbound — that, not
      `selected === null`, is what renders the placeholder. */
  triggerLabel: (job: T | null) => string
  /** Extra option content (urgent chip, status, rate). A RENDER prop, not an
      eager mapper: it runs only for the options actually drawn. The timesheet's
      rate lookup THROWS for a job with no workshop rate, so mapping every job
      up front would move that crash from "the option was visible" to "the grid
      loaded". */
  renderOptionDetail?: (job: T) => ReactNode
  /** Badge beside the trigger label — the trigger has room for a flag, not for
      the option row's status/company/rate block. */
  renderTriggerBadge?: (job: T) => ReactNode
  /** Cap on TYPED results; the blank-search list is never capped. */
  typedSearchLimit: number | null
  /** Tab commits the highlighted match. True only where the grid's Tab IS the
      row's forward-commit key (the timesheet grid). Where Tab is plain focus
      movement, committing would bind the first listed job to a cell the user
      only tabbed through. */
  commitOnTab: boolean
  /** data-entry-seq on the trigger; the keyboard-nav spec binds rows by it. */
  entrySeq?: number | null
  /** Runs the screen's background search for a term, in parallel with the
      local filter. Omit it where there is nothing beyond the local list to
      reach (leave settings holds every special job already). Its results are
      APPENDED below the local ones, never merged into them — see the merge
      below for why that ordering is load-bearing. */
  useJobSearch?: (term: string) => BackgroundJobSearch<T>
  onSelect: (job: T) => void
}

/** The picker's own match rule. Opus: Deliberately the same one
    apps/job/services/job_search.py applies, so the instant half of the list and
    the background half agree on what a term matches. */
function matchesTerm(job: JobPickerOption, loweredTerm: string): boolean {
  return (
    String(job.job_number).toLowerCase().includes(loweredTerm) ||
    job.name.toLowerCase().includes(loweredTerm) ||
    (job.company_name ?? '').toLowerCase().includes(loweredTerm)
  )
}

/** The no-background-search default. Uses no hooks, so standing in for a hook
    is safe; it exists so the real one can be called unconditionally. */
function useNoJobSearch<T extends JobPickerOption>(_term: string): BackgroundJobSearch<T> {
  return { jobs: NO_BACKGROUND_JOBS, isFetching: false, isError: false }
}

function statusLabel(status: string): string {
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

/**
 * The one job picker: a Radix popover with a search field, a maintained
 * highlight index, Enter picking the highlighted (or sole) match, and — where
 * the host grid asks for it — Tab picking the highlighted match so the caller
 * can move focus on.
 *
 * Not cmdk (which ItemSelect does use): that keyboard contract is v1's and
 * fights cmdk's internal selection model rather than reusing it.
 *
 * Radix rather than the hand-rolled body portal the PO grid used to carry: the
 * grid lives in an overflow-x-auto container that clips an absolutely
 * positioned dropdown, and Radix's portal is the library answer to that
 * (ADR 0032) — it also retires a manual getBoundingClientRect reposition and a
 * 150ms blur-grace timer that existed only to beat the dropdown's own unmount.
 */
export function JobPicker<T extends JobPickerOption>({
  automationIdPrefix,
  ariaLabel,
  jobs,
  selected,
  disabled,
  loading,
  placeholder,
  triggerLabel,
  renderOptionDetail,
  renderTriggerBadge,
  typedSearchLimit,
  commitOnTab,
  entrySeq = null,
  useJobSearch,
  onSelect,
}: JobPickerProps<T>) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [highlighted, setHighlighted] = useState(-1)
  const searchRef = useRef<HTMLInputElement>(null)
  // Set while closing because of a pick: the caller may move focus (to the
  // hours cell), so Radix's default focus-restore-to-trigger must not run.
  // An Escape/outside close keeps the default restore.
  const pickedRef = useRef(false)
  // Set while an Escape/outside close restores focus to the trigger: the
  // trigger's auto-open-on-focus must not immediately reopen what the user
  // just closed.
  const suppressReopenRef = useRef(false)
  // Pointer interactions open through the Radix trigger toggle; the focus
  // auto-open is for KEYBOARD and programmatic arrival only (the create
  // flow's handoff). Auto-opening on pointer focus would fight the toggle:
  // mousedown focuses, the click then toggles the just-opened popover shut.
  const pointerDownRef = useRef(false)

  const local = useMemo<T[]>(() => {
    const term = search.trim().toLowerCase()
    if (!term) {
      // Blank search shows the whole (workload-bounded) list, selected first.
      if (selected) {
        return [selected, ...jobs.filter((job) => job.id !== selected.id)]
      }
      return [...jobs]
    }
    const matches = jobs.filter((job) => matchesTerm(job, term))
    return typedSearchLimit === null ? matches : matches.slice(0, typedSearchLimit)
  }, [jobs, search, selected, typedSearchLimit])

  // The term the background search may spend a request on: debounced so
  // keystrokes do not each become a query, and blank below the minimum or
  // while closed so the hook below is a no-op rather than a wasted round trip.
  // The minimum lives here rather than in each caller — the server enforces
  // the same one, and a screen should not be able to disagree with it.
  const debouncedSearch = useDebouncedValue(search.trim(), SEARCH_DEBOUNCE_MS)
  const searchableTerm =
    open && debouncedSearch.length >= MIN_SEARCH_TERM_LENGTH ? debouncedSearch : ''

  // Always called, so the hook count never varies between renders; a caller
  // with nothing beyond its local list omits the prop and gets the constant.
  // Callers pass a stable module-level function — swapping one in or out
  // mid-life would break the rules of hooks, and none does.
  const background = (useJobSearch ?? useNoJobSearch)(searchableTerm)

  // Local matches keep their positions and the background ones APPEND below.
  // Ordering is load-bearing twice over: a response landing mid-keystroke must
  // not renumber what the user is arrowing through, and the local block is the
  // answer that was already on screen — reordering it would make the picker
  // appear to disagree with itself as the network resolves.
  const filtered = useMemo<T[]>(() => {
    if (background.jobs.length === 0) return local
    const seen = new Set(local.map((job) => job.id))
    return [...local, ...background.jobs.filter((job) => !seen.has(job.id))]
  }, [local, background.jobs])
  const localCount = local.length

  // The default highlight is the first match, reset when the TERM changes —
  // not when the filtered array's identity changes, because a parent
  // re-render rebuilds the jobs array and would clobber arrow-key state.
  // Keyed on the LOCAL count specifically: background results arriving must
  // not reset a highlight the user has already moved.
  useEffect(() => {
    if (!open) return
    setHighlighted(localCount > 0 ? 0 : -1)
  }, [open, search, localCount])

  useEffect(() => {
    if (!open) {
      setSearch('')
      setHighlighted(-1)
    }
  }, [open])

  const pick = (job: T) => {
    pickedRef.current = true
    onSelect(job)
    setOpen(false)
  }

  const onSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      setOpen(false)
      return
    }
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
        if (!commitOnTab) break
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
      default:
        break
    }
  }

  const bound = triggerLabel(selected)
  const label = bound === '' ? placeholder : bound

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          title={label}
          aria-label={ariaLabel}
          className={`block w-full truncate rounded border border-transparent px-2 py-1 text-left text-sm hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-50 ${bound === '' ? 'text-slate-400' : ''}`}
          data-automation-id={`${automationIdPrefix}-trigger`}
          data-entry-seq={entrySeq ?? undefined}
          onPointerDown={() => {
            pointerDownRef.current = true
          }}
          onFocus={() => {
            const viaPointer = pointerDownRef.current
            pointerDownRef.current = false
            if (viaPointer) return
            if (suppressReopenRef.current) {
              suppressReopenRef.current = false
              return
            }
            // An empty enabled control opens straight into search — the create
            // flow's focus handoff lands here and must not need a click.
            if (!disabled && !selected) setOpen(true)
          }}
        >
          {label}
          {selected === null ? null : renderTriggerBadge?.(selected)}
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
            return
          }
          suppressReopenRef.current = true
        }}
      >
        <div className="border-b border-slate-200 p-2">
          <input
            ref={searchRef}
            value={search}
            placeholder="Search jobs… (job number, name, or company)"
            className="h-8 w-full rounded border border-slate-200 px-2 text-sm"
            data-automation-id={`${automationIdPrefix}-search`}
            role="combobox"
            aria-expanded={open}
            aria-controls={`${automationIdPrefix}-list`}
            aria-activedescendant={
              highlighted >= 0
                ? `${automationIdPrefix}-option-${filtered[highlighted]?.job_number}`
                : undefined
            }
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={onSearchKeyDown}
          />
        </div>
        <div
          id={`${automationIdPrefix}-list`}
          role="listbox"
          className="max-h-[300px] overflow-y-auto"
          data-automation-id={`${automationIdPrefix}-list`}
        >
          {loading && <div className="px-3 py-2 text-sm text-slate-500">Jobs are loading…</div>}
          {/* Held back while the background search is still running: "no jobs
              found" would be a claim the picker cannot yet make. */}
          {!loading && filtered.length === 0 && !background.isFetching && (
            <div className="px-3 py-2 text-sm italic text-slate-500">
              {search.trim() !== '' ? `No jobs found for "${search}"` : 'No jobs available'}
            </div>
          )}
          {filtered.map((job, index) => (
            <Fragment key={job.id}>
              {index === localCount && (
                // The boundary between what this screen holds and what the
                // background search reached. Labelled, because picking one of
                // these binds a job the screen's own list deliberately excludes.
                <div
                  className="border-b border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-slate-500"
                  data-automation-id={`${automationIdPrefix}-other-jobs`}
                >
                  Other jobs
                </div>
              )}
              <div
                id={`${automationIdPrefix}-option-${job.job_number}`}
                role="option"
                aria-selected={index === highlighted}
                className={`cursor-pointer border-b border-slate-100 px-3 py-2 text-sm last:border-b-0 ${index === highlighted ? 'bg-blue-50' : 'hover:bg-slate-50'}`}
                data-automation-id={`${automationIdPrefix}-option-${job.job_number}`}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => pick(job)}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="shrink-0 font-semibold text-slate-800">#{job.job_number}</span>
                  {statusLabel(job.status) && (
                    <span className="text-right text-[11px] font-medium leading-tight text-slate-500">
                      {statusLabel(job.status)}
                    </span>
                  )}
                </div>
                <div className="mt-0.5 break-words font-medium leading-tight text-slate-700">
                  {job.name}
                </div>
                <div className="text-xs leading-tight text-slate-500">
                  Company: {job.company_name ?? 'No Company'}
                </div>
                {renderOptionDetail?.(job)}
              </div>
            </Fragment>
          ))}
          {background.isFetching && (
            <div
              className="px-3 py-2 text-xs italic text-slate-500"
              data-automation-id={`${automationIdPrefix}-searching`}
            >
              Searching all jobs…
            </div>
          )}
          {background.isError && (
            // The local results are still correct and usable, so this reports
            // the shortfall rather than blanking what is already on screen.
            <div
              className="px-3 py-2 text-xs text-red-700"
              data-automation-id={`${automationIdPrefix}-search-failed`}
            >
              Could not search beyond this screen&rsquo;s jobs.
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
