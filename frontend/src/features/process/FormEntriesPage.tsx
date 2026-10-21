import { useState } from 'react'
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  processEntriesDestroyMutation,
  processEntriesListQueryKey,
  processEntriesPartialUpdateMutation,
  processFormsEntriesCreateMutation,
  processFormsEntriesListOptions,
  processFormsEntriesListQueryKey,
  processFormsRetrieveOptions,
  processStaffOptionsListOptions,
  type EntryOut,
  type EntryUpdateIn,
} from '@/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { meQueryOptions } from '@/features/auth'

import { AcknowledgementsPanel } from './AcknowledgementsPanel'
import { EntriesTable } from './EntriesTable'
import { EntryForm, type EntryFormSubmitBody } from './EntryForm'
import { EntryHistoryDialog } from './EntryHistoryDialog'
import { extractFields, requireDocumentType, requireFormStatus } from './formSchema'
import { LinkedEntriesDialog } from './LinkedEntriesDialog'

const PAGE_SIZE = 20

/** null-safe equality so `undefined` (untouched) and `null` (explicitly
    cleared) compare the same as the wire's own null. */
function sameRef(a: string | null, b: string | null): boolean {
  return (a ?? null) === (b ?? null)
}

/** dirty-only diff for the entry PATCH — a full `data` replace when it
    changed at all (EntryUpdateIn's own contract, apps/process/schemas.py),
    nothing else sent untouched. Compares `data` key-sorted so field order
    (schema order on submit vs. server storage order) never manufactures a
    false diff. */
function buildEntryPatch(existing: EntryOut, submitted: EntryFormSubmitBody): EntryUpdateIn {
  const patch: EntryUpdateIn = {}
  if (submitted.entry_date !== existing.entry_date) patch.entry_date = submitted.entry_date
  const sortedExisting = JSON.stringify(existing.data, Object.keys(existing.data).toSorted())
  const sortedSubmitted = JSON.stringify(submitted.data, Object.keys(submitted.data).toSorted())
  if (sortedExisting !== sortedSubmitted) patch.data = submitted.data
  if (!sameRef(submitted.staff, existing.staff)) patch.staff = submitted.staff
  if (!sameRef(submitted.job, existing.job)) patch.job = submitted.job
  if (!sameRef(submitted.parent_entry, existing.parent_entry))
    patch.parent_entry = submitted.parent_entry
  return patch
}

/**
 * One form's entries (/process-documents/forms/:category/:formId): the
 * add-entry card (hidden for a form with no schema), the paginated entries
 * table, and edit/history/links dialogs per row.
 */
export function FormEntriesPage({ formId }: { category: string; formId: string }) {
  const { t } = useTranslation('process')
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [editingEntry, setEditingEntry] = useState<EntryOut | null>(null)
  const [historyEntry, setHistoryEntry] = useState<EntryOut | null>(null)
  const [linksEntry, setLinksEntry] = useState<EntryOut | null>(null)
  const [archivingId, setArchivingId] = useState<string | null>(null)

  const formQuery = useQuery(processFormsRetrieveOptions({ path: { form_id: formId } }))
  const entriesQuery = useQuery(
    processFormsEntriesListOptions({
      path: { form_id: formId },
      query: { page, page_size: PAGE_SIZE },
    }),
  )
  const staffOptionsQuery = useQuery(processStaffOptionsListOptions())

  const createMutation = useMutation(processFormsEntriesCreateMutation())
  const updateMutation = useMutation(processEntriesPartialUpdateMutation())
  const archiveMutation = useMutation(processEntriesDestroyMutation())

  // Local closure, not a module export: only this page's own two entries
  // surfaces (this form's list, the cross-form flat list any other page may
  // hold) ever need invalidating from an entries write made here.
  async function invalidate(): Promise<void> {
    await queryClient.invalidateQueries({
      queryKey: processFormsEntriesListQueryKey({ path: { form_id: formId } }),
    })
    // Bare prefix: matches every variant of the cross-form list (any query
    // params a caller elsewhere added), same mechanism ProcessFormsPage's
    // save flow uses on processFormsListQueryKey().
    await queryClient.invalidateQueries({ queryKey: processEntriesListQueryKey() })
  }

  async function handleCreate(body: EntryFormSubmitBody): Promise<void> {
    try {
      await createMutation.mutateAsync({
        path: { form_id: formId },
        body: {
          entry_date: body.entry_date,
          data: body.data,
          staff: body.staff,
          job: body.job,
          parent_entry: body.parent_entry,
        },
      })
      await invalidate()
      toast.success(t('entriesPage.entrySaved'))
    } catch (error) {
      toast.error(apiErrorMessage(error, t('entriesPage.entrySaveFailed')))
    }
  }

  async function handleUpdate(entry: EntryOut, body: EntryFormSubmitBody): Promise<void> {
    const patch = buildEntryPatch(entry, body)
    if (Object.keys(patch).length === 0) {
      setEditingEntry(null)
      return
    }
    try {
      await updateMutation.mutateAsync({ path: { entry_id: entry.id }, body: patch })
      await invalidate()
      toast.success(t('entriesPage.entryUpdated'))
      setEditingEntry(null)
    } catch (error) {
      toast.error(apiErrorMessage(error, t('entriesPage.entryUpdateFailed')))
    }
  }

  async function handleArchive(entry: EntryOut): Promise<void> {
    if (!window.confirm(t('entriesPage.archiveConfirm'))) return
    setArchivingId(entry.id)
    try {
      await archiveMutation.mutateAsync({ path: { entry_id: entry.id } })
      await invalidate()
      toast.success(t('entriesPage.entryArchived'))
    } catch (error) {
      toast.error(apiErrorMessage(error, t('entriesPage.entryArchiveFailed')))
    } finally {
      setArchivingId(null)
    }
  }

  if (formQuery.isPending || staffOptionsQuery.isPending) {
    return <p className="p-6 text-sm text-slate-500">{t('entriesPage.loading')}</p>
  }
  if (formQuery.isError || formQuery.data === undefined) {
    return <p className="p-6 text-sm font-medium text-red-700">{t('entriesPage.formFailed')}</p>
  }
  if (staffOptionsQuery.isError || staffOptionsQuery.data === undefined) {
    return <p className="p-6 text-sm font-medium text-red-700">{t('entriesPage.staffFailed')}</p>
  }

  const form = formQuery.data
  const staffOptions = staffOptionsQuery.data
  const schema = extractFields(form.form_schema)
  const totalPages = entriesQuery.data?.total_pages ?? 1

  return (
    <div className="min-h-screen p-6" data-automation-id="FormEntriesPage-root">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold text-gray-900" data-automation-id="FormEntries-title">
            {form.title}
          </h1>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-600">
            {form.document_number && (
              <span className="rounded bg-slate-100 px-2 py-0.5">{form.document_number}</span>
            )}
            <span className="rounded bg-slate-100 px-2 py-0.5">
              {t(`entriesPage.documentType.${requireDocumentType(form.document_type)}`)}
            </span>
            <span className="rounded bg-slate-100 px-2 py-0.5">
              {t(`entriesPage.status.${requireFormStatus(form.status)}`)}
            </span>
          </div>
          <AcknowledgementsPanel formId={formId} />
        </div>
      </div>

      {schema.length === 0 ? (
        <p className="mt-4 text-sm text-slate-600" data-automation-id="FormEntries-no-schema">
          {t('entriesPage.noSchema')}
        </p>
      ) : (
        <div
          className="mt-4 rounded-md border border-slate-200 p-4"
          data-automation-id="FormEntries-add-entry"
        >
          <h2 className="mb-3 text-sm font-semibold text-slate-700">{t('entriesPage.addEntry')}</h2>
          <EntryForm
            schema={schema}
            initial={{ staff: user.id }}
            staffOptions={staffOptions}
            submitting={createMutation.isPending}
            automationIdPrefix="EntryForm"
            onSubmit={handleCreate}
          />
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        <h2 data-automation-id="FormEntries-entries-count" className="text-lg font-semibold">
          {t('entriesPage.entriesCount', { count: entriesQuery.data?.count ?? 0 })}
        </h2>
        {totalPages > 1 && (
          <div className="flex items-center gap-2 text-sm">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((current) => current - 1)}
              data-automation-id="FormEntries-page-prev"
            >
              {t('entriesPage.previous')}
            </Button>
            <span className="text-slate-600">{t('entriesPage.pageOf', { page, totalPages })}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((current) => current + 1)}
              data-automation-id="FormEntries-page-next"
            >
              {t('entriesPage.next')}
            </Button>
          </div>
        )}
      </div>

      <EntriesTable
        schema={schema}
        isPending={entriesQuery.isPending}
        isError={entriesQuery.isError}
        onRetry={() => void entriesQuery.refetch()}
        rows={entriesQuery.data?.results}
        archivingId={archivingId}
        onEdit={setEditingEntry}
        onHistory={setHistoryEntry}
        onLinks={setLinksEntry}
        onArchive={(entry) => void handleArchive(entry)}
      />

      {editingEntry !== null && (
        <Dialog
          open
          onOpenChange={(next) => {
            if (!next && !updateMutation.isPending) setEditingEntry(null)
          }}
        >
          <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t('entriesPage.editEntry')}</DialogTitle>
            </DialogHeader>
            <EntryForm
              schema={schema}
              initial={editingEntry}
              staffOptions={staffOptions}
              submitting={updateMutation.isPending}
              automationIdPrefix="EntryForm-edit"
              onSubmit={(body) => handleUpdate(editingEntry, body)}
            />
          </DialogContent>
        </Dialog>
      )}

      <EntryHistoryDialog entry={historyEntry} onClose={() => setHistoryEntry(null)} />
      <LinkedEntriesDialog
        entry={linksEntry}
        staffOptions={staffOptions}
        currentStaffId={user.id}
        onClose={() => setLinksEntry(null)}
        onChanged={() => void invalidate()}
      />
    </div>
  )
}
