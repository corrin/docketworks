import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  processFormsEntriesListOptions,
  purchasingAllJobsRetrieveOptions,
  type FormFieldSchema,
} from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { JobPicker, type JobPickerOption } from '@/features/shared/JobPicker'
import { localIsoDate } from '@/lib/format'

import { textFor } from './entryValue'

export interface StaffOption {
  id: string
  name: string
}

/**
 * The seed EntryForm renders from: a full `EntryOut` in edit mode (extra
 * fields ignored structurally), or a partial "preset" object in create mode
 * — the add-entry card seeds only `staff` (the signed-in user) and the
 * linked-entry flow seeds only `parent_entry`.
 */
export interface EntryFormInitial {
  entry_date?: string
  staff?: string | null
  job?: string | null
  parent_entry?: string | null
  data?: Record<string, unknown>
}

export interface EntryFormSubmitBody {
  entry_date: string
  data: Record<string, string | number | boolean>
  staff: string | null
  job: string | null
  parent_entry: string | null
}

interface Props {
  schema: FormFieldSchema[]
  initial?: EntryFormInitial | null
  staffOptions: StaffOption[]
  onSubmit: (body: EntryFormSubmitBody) => void | Promise<void>
  submitting: boolean
  /** Every id EntryForm renders is `${automationIdPrefix}-...`. Callers that
      may mount more than one EntryForm at once (the entries page's
      always-present add-entry card plus a row's edit dialog) pass distinct
      prefixes so the two do not collide in the DOM; the single-instance
      call sites (the Fill dialog, FormDialog's preview) pass the bare
      "EntryForm" the required automation ids below assume. */
  automationIdPrefix: string
  disabled?: boolean
}

type Draft = string | boolean

function draftFor(field: FormFieldSchema, raw: unknown): Draft {
  if (field.type === 'boolean') return raw === true
  return textFor(raw)
}

function initialDrafts(schema: FormFieldSchema[], data: Record<string, unknown> | undefined) {
  return Object.fromEntries(
    schema.map((field) => [field.key, draftFor(field, data?.[field.key])]),
  ) as Record<string, Draft>
}

function isBlank(draft: Draft): boolean {
  return draft === ''
}

// The complement of every field type with its own branch below
// (entry_ref/boolean/textarea/select/staff): Exclude only DROPS the named
// members, so when the backend adds a new FieldType it is NOT named here and
// therefore lands IN SimpleFieldType — which makes the Record below miss a
// property and fail to compile until either a new branch or a new INPUT_TYPE
// entry handles it (the same mechanism as SettingsFieldInput.tsx:33-36; an
// Extract of the three names here would do the opposite — a new type would
// silently stay out of SimpleFieldType and this Record would keep compiling).
type SimpleFieldType = Exclude<
  FormFieldSchema['type'],
  'entry_ref' | 'boolean' | 'textarea' | 'select' | 'staff'
>
const INPUT_TYPE: Record<SimpleFieldType, string> = {
  text: 'text',
  number: 'number',
  date: 'date',
}

// Derived from INPUT_TYPE's own keys rather than a second hand-maintained
// list of type names, so there is exactly one place that enumerates
// SimpleFieldType's members.
function isSimpleFieldType(type: FormFieldSchema['type']): type is SimpleFieldType {
  return type in INPUT_TYPE
}

interface FieldProps {
  field: FormFieldSchema
  draft: Draft
  onChange: (draft: Draft) => void
  disabled: boolean
  staffOptions: StaffOption[]
  automationId: string
}

/** entry_ref's own component: its options load from ANOTHER form's entries,
    which needs a query hook — pulling that into a per-field branch inside a
    schema.map() loop would call useQuery a variable number of times across
    renders, breaking the rules of hooks. */
function EntryRefField({ field, draft, onChange, disabled, automationId }: FieldProps) {
  if (field.source_form === undefined || field.source_form === null) {
    // FormFieldSchema._coherent guarantees source_form whenever type is
    // entry_ref (apps/process/schemas.py); a stored schema that violates
    // this is data damage to surface, not a value to fall back over.
    throw new Error(`Field '${field.key}' is type entry_ref but has no source_form.`)
  }
  const sourceFormId = field.source_form
  const entriesQuery = useQuery(
    processFormsEntriesListOptions({ path: { form_id: sourceFormId }, query: { page_size: 100 } }),
  )
  const rows = entriesQuery.data?.results ?? []
  const displayKey = field.display_key ?? ''
  return (
    <select
      className={INPUT_CLASS}
      value={typeof draft === 'string' ? draft : ''}
      disabled={disabled || entriesQuery.isPending}
      onChange={(event) => onChange(event.target.value)}
      aria-label={field.label}
      data-automation-id={automationId}
    >
      <option value="">{entriesQuery.isPending ? 'Loading…' : 'Select…'}</option>
      {rows.map((entry) => {
        const label = entry.display_data[displayKey] || textFor(entry.data[displayKey]) || entry.id
        return (
          <option key={entry.id} value={entry.id}>
            {label}
          </option>
        )
      })}
    </select>
  )
}

function SchemaField({ field, draft, onChange, disabled, staffOptions, automationId }: FieldProps) {
  if (field.type === 'entry_ref') {
    return (
      <EntryRefField
        field={field}
        draft={draft}
        onChange={onChange}
        disabled={disabled}
        staffOptions={staffOptions}
        automationId={automationId}
      />
    )
  }

  if (field.type === 'boolean') {
    return (
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300"
        checked={draft === true}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        aria-label={field.label}
        data-automation-id={automationId}
      />
    )
  }

  if (field.type === 'textarea') {
    return (
      <textarea
        className={`${INPUT_CLASS} min-h-24`}
        value={typeof draft === 'string' ? draft : ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-label={field.label}
        data-automation-id={automationId}
      />
    )
  }

  if (field.type === 'select') {
    return (
      <select
        className={INPUT_CLASS}
        value={typeof draft === 'string' ? draft : ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-label={field.label}
        data-automation-id={automationId}
      >
        <option value="">Select…</option>
        {(field.options ?? []).map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    )
  }

  if (field.type === 'staff') {
    return (
      <select
        className={INPUT_CLASS}
        value={typeof draft === 'string' ? draft : ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-label={field.label}
        data-automation-id={automationId}
      >
        <option value="">Select…</option>
        {staffOptions.map((option) => (
          <option key={option.id} value={option.id}>
            {option.name}
          </option>
        ))}
      </select>
    )
  }

  if (!isSimpleFieldType(field.type)) {
    // Unreachable while FieldType stays the closed union above — the
    // exhaustiveness check every branch before this one relies on.
    throw new Error(`Unhandled field type "${String(field.type)}".`)
  }

  return (
    <input
      type={INPUT_TYPE[field.type]}
      step={field.type === 'number' ? 'any' : undefined}
      className={INPUT_CLASS}
      value={typeof draft === 'string' ? draft : ''}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      aria-label={field.label}
      data-automation-id={automationId}
    />
  )
}

/**
 * The ONE schema-driven entry component: the entries page's add-entry card,
 * a row's edit dialog, the forms-list Fill dialog, and FormDialog's disabled
 * preview all render this — one implementation of "render a form from
 * FormFieldSchema[]" (ADR 0039), never a per-surface sibling.
 */
export function EntryForm({
  schema,
  initial,
  staffOptions,
  onSubmit,
  submitting,
  automationIdPrefix,
  disabled = false,
}: Props) {
  const [entryDate, setEntryDate] = useState(initial?.entry_date ?? localIsoDate())
  const [staffId, setStaffId] = useState(initial?.staff ?? '')
  const [jobId, setJobId] = useState<string | null>(initial?.job ?? null)
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    initialDrafts(schema, initial?.data),
  )
  const [validationError, setValidationError] = useState<string | null>(null)

  // The optional job link: reuses the PO grid's "all non-archived jobs"
  // endpoint (frontend/src/features/purchasing/PoLinesTable.tsx:91) — the
  // one general, company-unscoped job list already wired to the shared
  // JobPicker, unlike purchasing's own usePoJobSearch background search
  // (a PO-specific `q` reach into archived jobs this simpler picker skips).
  // NOT timesheetsJobsRetrieveOptions: although the my-time slice made that
  // endpoint self-service too, its payload is time-entry pricing (labour
  // rates, pay items, shop_job) this form never reads — the plain list is
  // the narrower fit.
  const jobsQuery = useQuery(purchasingAllJobsRetrieveOptions())
  const jobs = jobsQuery.data?.jobs ?? []
  const selectedJob: JobPickerOption | null = jobs.find((job) => job.id === jobId) ?? null

  const setDraft = (key: string, draft: Draft): void => {
    setDrafts((previous) => ({ ...previous, [key]: draft }))
  }

  function localProblem(): string | null {
    for (const field of schema) {
      if (!field.required) continue
      const draft = drafts[field.key]
      if (draft === undefined || isBlank(draft)) return `'${field.label}' is required.`
    }
    return null
  }

  async function handleSubmit(): Promise<void> {
    if (disabled || submitting) return
    const problem = localProblem()
    if (problem !== null) {
      setValidationError(problem)
      return
    }
    setValidationError(null)
    const data: Record<string, string | number | boolean> = {}
    for (const field of schema) {
      const draft = drafts[field.key]
      if (field.type === 'boolean') {
        data[field.key] = draft === true
        continue
      }
      // A blank optional field is omitted, not sent as "": the server's
      // per-type checkers (apps/process/services/entry_validation.py) run on
      // any PRESENT key regardless of `required`, and an empty string fails
      // every checker but text/textarea.
      if (draft === undefined || isBlank(draft)) continue
      data[field.key] = field.type === 'number' ? Number(draft) : String(draft)
    }
    await onSubmit({
      entry_date: entryDate,
      data,
      staff: staffId === '' ? null : staffId,
      job: jobId,
      parent_entry: initial?.parent_entry ?? null,
    })
  }

  return (
    <div className="flex flex-col gap-4" data-automation-id={`${automationIdPrefix}-root`}>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm font-medium">
          <span className="text-slate-700">Entry date</span>
          <input
            type="date"
            className={INPUT_CLASS}
            value={entryDate}
            disabled={disabled}
            onChange={(event) => setEntryDate(event.target.value)}
            data-automation-id={`${automationIdPrefix}-entry-date`}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          <span className="text-slate-700">Signed by</span>
          <select
            className={INPUT_CLASS}
            value={staffId ?? ''}
            disabled={disabled}
            onChange={(event) => setStaffId(event.target.value)}
            data-automation-id={`${automationIdPrefix}-staff`}
          >
            <option value="">Select staff…</option>
            {staffOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-col gap-1 text-sm font-medium md:col-span-2">
          <span className="text-slate-700">Job (optional)</span>
          <div className="flex items-center gap-2">
            <div className="flex-1 rounded-md border border-slate-200">
              <JobPicker
                automationIdPrefix={`${automationIdPrefix}-job`}
                ariaLabel="Linked job"
                jobs={jobs}
                selected={selectedJob}
                disabled={disabled}
                loading={jobsQuery.isPending}
                placeholder="No job linked"
                triggerLabel={(job) => (job === null ? '' : `#${job.job_number} - ${job.name}`)}
                typedSearchLimit={null}
                commitOnTab={false}
                onSelect={(job) => setJobId(job.id)}
              />
            </div>
            {/* JobPicker's onSelect only hands back a chosen job, never null —
                there is no way to clear the link from inside the picker
                itself, so a plain secondary button submits job: null. */}
            {selectedJob !== null && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={disabled}
                onClick={() => setJobId(null)}
                data-automation-id={`${automationIdPrefix}-job-clear`}
              >
                Clear
              </Button>
            )}
          </div>
        </div>
      </div>

      {schema.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {schema.map((field) => (
            <label key={field.key} className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">
                {field.label}
                {field.required && <span className="text-red-600"> *</span>}
              </span>
              <SchemaField
                field={field}
                draft={drafts[field.key] ?? (field.type === 'boolean' ? false : '')}
                onChange={(draft) => setDraft(field.key, draft)}
                disabled={disabled}
                staffOptions={staffOptions}
                automationId={`${automationIdPrefix}-field-${field.key}`}
              />
            </label>
          ))}
        </div>
      )}

      {validationError && (
        <p
          role="alert"
          className="text-sm text-red-700"
          data-automation-id={`${automationIdPrefix}-validation`}
        >
          {validationError}
        </p>
      )}

      <div>
        <Button
          disabled={disabled || submitting}
          onClick={() => void handleSubmit()}
          data-automation-id={`${automationIdPrefix}-submit`}
        >
          {submitting ? 'Saving…' : 'Save entry'}
        </Button>
      </div>
    </div>
  )
}
