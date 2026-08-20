import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker } from '@tanstack/react-router'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobJobsOptionsListOptions,
  timesheetsLeaveSettingsRetrieveOptions,
  timesheetsLeaveSettingsRetrieveQueryKey,
  timesheetsLeaveSettingsUpdateMutation,
  xeroPayItemsListOptions,
  type LeaveSettingsOut,
  type JobOptionOut,
  type LeaveTypeOut,
  type XeroPayItemOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { JobPicker } from '@/features/shared/JobPicker'
import { QueryState } from '@/features/shared/QueryState'
import { INPUT_CLASS } from '@/components/ui/field'

/** One row's editable values. Unset ids are null, never '' (ADR 0040): '' is
    the select element's sentinel and stops at that boundary. */
interface LeaveDraft {
  display_name: string
  job_id: string | null
  xero_pay_item_id: string | null
}

type LeaveDrafts = Record<string, LeaveDraft>

function snapshotLeaveSettings(settings: LeaveSettingsOut): LeaveDrafts {
  const drafts: LeaveDrafts = {}
  for (const type of settings.leave_types) {
    drafts[type.code] = {
      display_name: type.display_name,
      job_id: type.job_id,
      xero_pay_item_id: type.xero_pay_item_id,
    }
  }
  return drafts
}

// Compared field by field rather than by JSON.stringify: v1 stringified only
// because its field list was schema-driven `unknown`. Here the shape is a
// named three-field type, and a typed comparison is the contract (ADR 0028).
function sameDraft(a: LeaveDraft, b: LeaveDraft): boolean {
  return (
    a.display_name === b.display_name &&
    a.job_id === b.job_id &&
    a.xero_pay_item_id === b.xero_pay_item_id
  )
}

function isComplete(draft: LeaveDraft, type: LeaveTypeOut): boolean {
  if (draft.display_name.trim() === '' || draft.job_id === null) return false
  // An xero_computed row HAS no Xero item to select — Xero pays it from its
  // own calculation — so a null there is the finished state, not a gap.
  return type.posting_surface === 'xero_computed' || draft.xero_pay_item_id !== null
}

/** The five codes are seeded by migration, so a code the server returned and
    the snapshot lacks is a programming error, not a case to default around
    (ADR 0015). */
function requireDraft(drafts: LeaveDrafts, code: string): LeaveDraft {
  const draft = drafts[code]
  if (draft === undefined) throw new Error(`Leave settings snapshot is missing ${code}.`)
  return draft
}

/** A complete row reduced to the wire shape. Narrows the nullable ids once,
    at the boundary that requires them, instead of asserting at each use. */
function updatePayload(type: LeaveTypeOut, draft: LeaveDraft) {
  const { job_id, xero_pay_item_id } = draft
  if (job_id === null) {
    throw new Error(`${type.code} was submitted without a Job.`)
  }
  if (type.posting_surface === 'xero_computed') {
    // Null on the wire is the truthful value for this surface — there is no
    // Xero object to name — and the server refuses anything else.
    return {
      code: type.code,
      display_name: draft.display_name.trim(),
      job_id,
      xero_pay_item_id: null,
    }
  }
  if (xero_pay_item_id === null) {
    throw new Error(`${type.code} was submitted without a Xero payroll item.`)
  }
  return { code: type.code, display_name: draft.display_name.trim(), job_id, xero_pay_item_id }
}

export function LeaveSettingsPage() {
  const settingsQuery = useQuery(timesheetsLeaveSettingsRetrieveOptions())
  const payItemsQuery = useQuery(xeroPayItemsListOptions())
  // Only special jobs back a leave type, so the server sends only those —
  // rather than the timesheet list, which carries labour rates and estimates
  // this picker never draws.
  const jobsQuery = useQuery(jobJobsOptionsListOptions({ query: { status: 'special' } }))

  return (
    <main
      className="flex min-h-0 flex-col space-y-5 p-5"
      data-automation-id="LeaveSettingsPage-root"
    >
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Leave settings</h1>
        <p className="text-sm text-slate-500">
          Map each fixed Docketworks leave type to its special Job and Xero payroll item.
        </p>
      </header>
      <QueryState
        isPending={settingsQuery.isPending || payItemsQuery.isPending || jobsQuery.isPending}
        isError={settingsQuery.isError || payItemsQuery.isError || jobsQuery.isError}
        loadingNode={<p className="text-sm text-slate-500">Loading leave settings…</p>}
        errorNode={<p className="text-sm text-red-700">Could not load leave settings.</p>}
      >
        {settingsQuery.data && payItemsQuery.data && jobsQuery.data && (
          <LeaveSettingsForm
            settings={settingsQuery.data}
            payItems={payItemsQuery.data}
            jobs={jobsQuery.data.jobs}
          />
        )}
      </QueryState>
    </main>
  )
}

function LeaveSettingsForm({
  settings,
  payItems,
  jobs,
}: {
  settings: LeaveSettingsOut
  payItems: XeroPayItemOut[]
  jobs: JobOptionOut[]
}) {
  // Two copies, exactly v1's server snapshot and edited form. Both are seeded
  // ONCE and advance together only on a successful save.
  //
  // No effect re-hydrates them from `settings`. That was the bug this replaces:
  // any background refetch — window focus, the 30s staleTime expiring, the
  // save's own invalidation — produced new props and wiped whatever the admin
  // had typed. Read-only display below still reads the live `settings` prop,
  // so status stays current while edits survive.
  const [server, setServer] = useState<LeaveDrafts>(() => snapshotLeaveSettings(settings))
  const [drafts, setDrafts] = useState<LeaveDrafts>(() => snapshotLeaveSettings(settings))
  const [saving, setSaving] = useState(false)
  const queryClient = useQueryClient()
  const updateMutation = useMutation(timesheetsLeaveSettingsUpdateMutation())

  const dirtyCodes = useMemo(
    () =>
      settings.leave_types
        .map((type) => type.code)
        .filter((code) => !sameDraft(requireDraft(drafts, code), requireDraft(server, code))),
    [drafts, server, settings.leave_types],
  )
  const incompleteCodes = settings.leave_types
    .filter((type) => dirtyCodes.includes(type.code))
    .filter((type) => !isComplete(requireDraft(drafts, type.code), type))
    .map((type) => type.code)
  const isDirty = dirtyCodes.length > 0
  const canSave = isDirty && incompleteCodes.length === 0 && !saving

  // TanStack Router blocks when shouldBlockFn returns true, so a confirmed
  // discard is the negation. `disabled` arms it — calling the hook
  // conditionally would break the rules of hooks. enableBeforeUnload covers
  // tab-close, which v1's onBeforeRouteLeave never did.
  useBlocker({
    shouldBlockFn: () =>
      !window.confirm('You have unsaved changes. Discard them and leave this page?'),
    disabled: !isDirty,
    enableBeforeUnload: () => isDirty,
  })

  const setDraft = (code: string, patch: Partial<LeaveDraft>) => {
    setDrafts((current) => ({ ...current, [code]: { ...requireDraft(current, code), ...patch } }))
  }

  const save = async () => {
    setSaving(true)
    try {
      // Only changed rows: a leave type may legitimately be unmapped, and
      // submitting it would 422 the whole save.
      const fresh = await updateMutation.mutateAsync({
        body: {
          leave_types: settings.leave_types
            .filter((type) => dirtyCodes.includes(type.code))
            .map((type) => updatePayload(type, requireDraft(drafts, type.code))),
        },
      })
      // The PATCH returns the post-save page state computed inside its own
      // transaction, so the cache and both snapshots refresh in one hop.
      // v1 needed a second GET only because its update returned nothing usable;
      // queryClient.fetchQuery would NOT work here — the 30s staleTime makes it
      // a cache read, leaving the page dirty after a successful save.
      queryClient.setQueryData(timesheetsLeaveSettingsRetrieveQueryKey(), fresh)
      setServer(snapshotLeaveSettings(fresh))
      setDrafts(snapshotLeaveSettings(fresh))
      toast.success('Leave settings saved')
    } catch (error) {
      // The server's own message is the diagnosis ("Annual Leave requires a
      // Xero leave type."); v1's static string threw it away.
      toast.error(apiErrorMessage(error, 'Could not save leave settings.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="flex-1 overflow-y-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Docketworks leave type</th>
              <th className="px-3 py-2">Docketworks Job</th>
              <th className="px-3 py-2">Xero payroll item</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {settings.leave_types.map((type) => (
              <SettingsRow
                key={type.code}
                type={type}
                draft={requireDraft(drafts, type.code)}
                jobs={jobs}
                payItems={payItems.filter((item) => item.uses_leave_api)}
                incomplete={incompleteCodes.includes(type.code)}
                onChange={(patch) => setDraft(type.code, patch)}
              />
            ))}
          </tbody>
        </table>
      </div>
      <div
        className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-white/75"
        data-automation-id="LeaveSettingsPage-footer"
      >
        <Button
          variant="outline"
          disabled={saving || !isDirty}
          data-automation-id="LeaveSettingsPage-cancel-button"
          onClick={() => setDrafts(server)}
        >
          Cancel
        </Button>
        <Button
          disabled={!canSave}
          data-automation-id="LeaveSettingsPage-save-button"
          onClick={() => void save()}
        >
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </>
  )
}

function SettingsRow({
  type,
  draft,
  jobs,
  payItems,
  incomplete,
  onChange,
}: {
  type: LeaveTypeOut
  draft: LeaveDraft
  jobs: readonly JobOptionOut[]
  payItems: XeroPayItemOut[]
  incomplete: boolean
  onChange: (patch: Partial<LeaveDraft>) => void
}) {
  const selectedJob = jobs.find((job) => job.id === draft.job_id) ?? null

  return (
    <tr
      className="border-t border-slate-100"
      data-automation-id={`LeaveSettingsPage-row-${type.code}`}
    >
      <td className="min-w-52 px-3 py-3">
        <input
          aria-label={`${type.code} display name`}
          className={INPUT_CLASS}
          value={draft.display_name}
          onChange={(event) => onChange({ display_name: event.target.value })}
        />
        <p className="mt-1 text-xs text-slate-400">{type.code}</p>
      </td>
      <td className="min-w-52 px-3 py-3">
        <JobPicker
          automationIdPrefix={`LeaveSettingsPage-job-${type.code}`}
          ariaLabel={`${type.code} job`}
          jobs={jobs}
          selected={selectedJob}
          disabled={false}
          loading={false}
          placeholder="Select special Job"
          triggerLabel={(job) => job?.name ?? ''}
          typedSearchLimit={null}
          commitOnTab={false}
          onSelect={(job) => onChange({ job_id: job.id })}
        />
      </td>
      <td className="min-w-52 px-3 py-3">
        {/* Xero computes public-holiday pay from the employee's working pattern and
            exposes no endpoint to create or suppress it, so there is nothing to map
            here — and offering a Xero item would post the day a second time. */}
        {type.posting_surface === 'xero_computed' ? (
          <p
            className="text-xs text-slate-500"
            data-automation-id={`LeaveSettingsPage-computed-${type.code}`}
          >
            Paid by Xero&rsquo;s own calculation. Docketworks records these hours and posts nothing
            for them.
          </p>
        ) : (
          <select
            aria-label={`${type.code} Xero item`}
            className={INPUT_CLASS}
            value={draft.xero_pay_item_id ?? ''}
            onChange={(event) => onChange({ xero_pay_item_id: event.target.value || null })}
          >
            <option value="">Select Xero leave type</option>
            {payItems
              .filter((item) => item.xero_id !== null)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
        )}
      </td>
      <td className="px-3 py-3">
        <span className={type.configured ? 'text-emerald-700' : 'text-amber-700'}>
          {type.configured ? 'Configured' : 'Needs configuration'}
        </span>
        {incomplete && (
          <p
            className="mt-1 text-xs text-amber-700"
            data-automation-id={`LeaveSettingsPage-row-${type.code}-incomplete`}
          >
            {type.posting_surface === 'xero_computed'
              ? 'Select a Job before saving.'
              : 'Select a Job and a Xero payroll item before saving.'}
          </p>
        )}
      </td>
    </tr>
  )
}
