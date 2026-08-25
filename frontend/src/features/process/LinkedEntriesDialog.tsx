import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  processEntriesListOptions,
  processEntriesListQueryKey,
  processFormsEntriesCreateMutation,
  processFormsListOptions,
  type EntryOut,
  type FormOut,
} from '@/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { INPUT_CLASS } from '@/components/ui/field'
import { QueryState } from '@/features/shared/QueryState'
import { formatDate } from '@/lib/format'

import { EntryForm, type EntryFormSubmitBody, type StaffOption } from './EntryForm'
import { textFor } from './entryValue'
import { extractFields } from './formSchema'

interface Props {
  /** The entry whose children are shown, or null while the dialog is closed. */
  entry: EntryOut | null
  staffOptions: StaffOption[]
  /** Seeds the "add linked entry" form's staff picker, same as the entries
      page's own add-entry card — the signed-in user. */
  currentStaffId: string
  onClose: () => void
  /** Fired after a linked entry is created, so the caller can invalidate
      whatever entries lists it owns (the parent's own row's child_count
      among them). */
  onChanged: () => void
}

interface ChildGroup {
  formId: string
  title: string
  children: EntryOut[]
}

function groupByForm(rows: EntryOut[], formsById: Map<string, FormOut>): ChildGroup[] {
  const byForm = new Map<string, EntryOut[]>()
  for (const row of rows) {
    const existing = byForm.get(row.form)
    if (existing) existing.push(row)
    else byForm.set(row.form, [row])
  }
  return [...byForm.entries()].map(([formId, children]) => ({
    formId,
    title: formsById.get(formId)?.title ?? 'Unknown form',
    children,
  }))
}

/** A short label for one child row: its first couple of data fields,
    display-resolved where the server resolved them. Falls back to the
    entry's id for a schema with no fields to summarise. */
function summarize(entry: EntryOut): string {
  const parts = Object.entries(entry.data)
    .slice(0, 2)
    .map(([key, value]) => {
      const displayed = entry.display_data[key]
      const text = displayed ?? textFor(value)
      return `${key}: ${text === '' ? '-' : text}`
    })
  return parts.length > 0 ? parts.join(', ') : entry.id
}

/**
 * An entry's children, grouped by their form's title, plus "add linked
 * entry": pick a form, then fill it with `parent_entry` preset to this
 * entry — the same `EntryForm` every other write surface in this feature
 * renders (ADR 0039).
 */
export function LinkedEntriesDialog({
  entry,
  staffOptions,
  currentStaffId,
  onClose,
  onChanged,
}: Props) {
  return (
    <Dialog
      open={entry !== null}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      {/* Keyed on the entry so switching rows resets which form is being
          added; mounted only while open so the body takes a non-null entry
          with no nullable dance at every use. */}
      {entry !== null && (
        <LinkedEntriesBody
          key={entry.id}
          entry={entry}
          staffOptions={staffOptions}
          currentStaffId={currentStaffId}
          onChanged={onChanged}
        />
      )}
    </Dialog>
  )
}

function LinkedEntriesBody({
  entry,
  staffOptions,
  currentStaffId,
  onChanged,
}: {
  entry: EntryOut
  staffOptions: StaffOption[]
  currentStaffId: string
  onChanged: () => void
}) {
  const queryClient = useQueryClient()
  const childrenQuery = useQuery(
    processEntriesListOptions({ query: { parent: entry.id, page_size: 100 } }),
  )
  // All forms, unfiltered: doubles as both the child-grouping label lookup
  // and the "add linked entry" form picker's option list, one query for both
  // rather than a per-child form fetch.
  const formsQuery = useQuery(processFormsListOptions())
  const createMutation = useMutation(processFormsEntriesCreateMutation())
  const [addingFormId, setAddingFormId] = useState('')

  const formsById = useMemo(
    () => new Map((formsQuery.data ?? []).map((form) => [form.id, form])),
    [formsQuery.data],
  )
  const groups = useMemo(
    () => groupByForm(childrenQuery.data?.results ?? [], formsById),
    [childrenQuery.data, formsById],
  )
  const addingForm = addingFormId === '' ? null : (formsById.get(addingFormId) ?? null)

  async function submitLinkedEntry(form: FormOut, body: EntryFormSubmitBody): Promise<void> {
    try {
      await createMutation.mutateAsync({
        path: { form_id: form.id },
        body: {
          entry_date: body.entry_date,
          data: body.data,
          staff: body.staff,
          job: body.job,
          parent_entry: body.parent_entry,
        },
      })
      await queryClient.invalidateQueries({ queryKey: processEntriesListQueryKey() })
      onChanged()
      toast.success('Linked entry saved')
      setAddingFormId('')
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Could not save the linked entry.'))
    }
  }

  return (
    <DialogContent
      className="max-h-[80vh] overflow-y-auto sm:max-w-2xl"
      data-automation-id="LinkedEntriesDialog-content"
    >
      <DialogHeader>
        <DialogTitle>Linked entries</DialogTitle>
      </DialogHeader>
      <QueryState
        isPending={childrenQuery.isPending}
        isError={childrenQuery.isError}
        onRetry={() => void childrenQuery.refetch()}
        loadingLabel="Loading linked entries..."
        errorLabel="Failed to load linked entries."
      >
        {groups.length === 0 ? (
          <p className="text-sm text-slate-500" data-automation-id="LinkedEntriesDialog-empty">
            No linked entries yet.
          </p>
        ) : (
          <div className="flex flex-col gap-4" data-automation-id="LinkedEntriesDialog-groups">
            {groups.map((group) => (
              <div key={group.formId}>
                <h3 className="text-sm font-semibold text-slate-700">{group.title}</h3>
                <ul className="mt-1 flex flex-col gap-1 text-sm text-slate-600">
                  {group.children.map((child) => (
                    <li key={child.id} data-automation-id={`LinkedEntriesDialog-child-${child.id}`}>
                      {formatDate(child.entry_date)} — {summarize(child)}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </QueryState>

      <div className="mt-4 flex flex-col gap-2 border-t border-slate-200 pt-4">
        <label className="flex flex-col gap-1 text-sm font-medium">
          <span className="text-slate-700">Add a linked entry</span>
          <select
            className={INPUT_CLASS}
            value={addingFormId}
            onChange={(event) => setAddingFormId(event.target.value)}
            data-automation-id="LinkedEntriesDialog-add-form"
          >
            <option value="">Choose a form…</option>
            {(formsQuery.data ?? []).map((form) => (
              <option key={form.id} value={form.id}>
                {form.title}
              </option>
            ))}
          </select>
        </label>
        {addingForm !== null &&
          (extractFields(addingForm.form_schema).length === 0 ? (
            <p className="text-sm text-slate-600">
              This document has no form schema defined. Entries cannot be added.
            </p>
          ) : (
            <EntryForm
              schema={extractFields(addingForm.form_schema)}
              initial={{ staff: currentStaffId, parent_entry: entry.id }}
              staffOptions={staffOptions}
              submitting={createMutation.isPending}
              automationIdPrefix={`EntryForm-link-${addingForm.id}`}
              onSubmit={(body) => submitLinkedEntry(addingForm, body)}
            />
          ))}
      </div>
    </DialogContent>
  )
}
