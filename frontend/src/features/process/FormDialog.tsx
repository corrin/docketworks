import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  processCategoriesRetrieveOptions,
  processFormsCreateMutation,
  processFormsListQueryKey,
  processFormsPartialUpdateMutation,
  type FormCreateIn,
  type FormOut,
  type FormSchemaSpec,
  type FormUpdateIn,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { INPUT_CLASS } from '@/components/ui/field'

import { EntryForm } from './EntryForm'
import { extractFields, isFormSchemaSpec } from './formSchema'

// apps/process/models.py Form.Category.choices define exactly these five
// keys; FormCreateIn/FormUpdateIn's category field mirrors them as a closed
// literal union on the wire, so a select value outside this set is a markup
// defect (ADR 0028) to fail on, not user input to coerce.
const CATEGORY_VALUES = ['safety', 'training', 'incident', 'meeting', 'register'] as const
type Category = (typeof CATEGORY_VALUES)[number]

export function isCategory(value: string): value is Category {
  return (CATEGORY_VALUES as readonly string[]).includes(value)
}

export function requireCategory(value: string): Category {
  if (!isCategory(value)) throw new Error(`Unexpected category "${value}".`)
  return value
}

const DOCUMENT_TYPE_VALUES = ['form', 'register'] as const
type DocumentType = (typeof DOCUMENT_TYPE_VALUES)[number]

function isDocumentType(value: string): value is DocumentType {
  return (DOCUMENT_TYPE_VALUES as readonly string[]).includes(value)
}

function requireDocumentType(value: string): DocumentType {
  if (!isDocumentType(value)) throw new Error(`Unexpected document type "${value}".`)
  return value
}

// Form.Status has exactly these two values; FormUpdateIn.status mirrors them
// as a closed literal union on the wire.
const FORM_STATUS_VALUES = ['active', 'archived'] as const
type FormStatus = (typeof FORM_STATUS_VALUES)[number]

function isFormStatus(value: string): value is FormStatus {
  return (FORM_STATUS_VALUES as readonly string[]).includes(value)
}

function requireFormStatus(value: string): FormStatus {
  if (!isFormStatus(value)) throw new Error(`Unexpected form status "${value}".`)
  return value
}

const DEFAULT_SCHEMA_TEXT = JSON.stringify({ fields: [] }, null, 2)

interface Drafts {
  title: string
  document_number: string
  category: string
  document_type: string
  tags: string
  /** The JSON source for form_schema; parsed live for validation and the preview. */
  schemaText: string
  /** Edit mode only — the create endpoint has no status field; a new form is
      always active. */
  status: string
}

function snapshot(form: FormOut | null): Drafts {
  return {
    title: form?.title ?? '',
    document_number: form?.document_number ?? '',
    category: form?.category ?? '',
    document_type: form?.document_type ?? '',
    tags: form ? form.tags.join(', ') : '',
    // Edit mode seeds the editor from the form's ACTUAL saved schema: v1's
    // edit form never loaded form_schema and never sent it back on save, so
    // every edit silently wiped the form's fields. Round-tripping through
    // this textarea (load, edit, PATCH back) is the fix this dialog exists
    // to ship.
    schemaText: form ? JSON.stringify(form.form_schema, null, 2) : DEFAULT_SCHEMA_TEXT,
    status: form?.status ?? 'active',
  }
}

/** '' means unset for the nullable text column (ADR 0040: null clears, blank
 * is a 422 — so an emptied box must become null on the wire, never ""). */
const textOrNull = (value: string): string | null => {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function tagsFromText(value: string): string[] {
  return value
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag !== '')
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** null = create a new form. */
  form: FormOut | null
}

/**
 * Create/edit modal for a form or register definition. The schema editor is
 * the whole point: a raw JSON textarea with a live parse check and a
 * label/type-badge preview, so the person defining a form's fields sees
 * immediately whether the JSON they typed is even well-formed before it
 * reaches the server's real structural validator.
 */
export function FormDialog({ open, onOpenChange, form }: Props) {
  const queryClient = useQueryClient()
  const categoriesQuery = useQuery(processCategoriesRetrieveOptions())
  const createMutation = useMutation(processFormsCreateMutation())
  const updateMutation = useMutation(processFormsPartialUpdateMutation())
  const [drafts, setDrafts] = useState<Drafts>(() => snapshot(form))
  const [validationError, setValidationError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setDrafts(snapshot(form))
    setValidationError(null)
  }, [open, form])

  const setDraft = <K extends keyof Drafts>(key: K, value: Drafts[K]): void => {
    setDrafts((previous) => ({ ...previous, [key]: value }))
  }

  const parsedSchema = useMemo(() => {
    try {
      const value: unknown = JSON.parse(drafts.schemaText)
      return { ok: true as const, value }
    } catch (error) {
      return {
        ok: false as const,
        message: error instanceof Error ? error.message : 'Invalid JSON',
      }
    }
  }, [drafts.schemaText])

  const previewFields = parsedSchema.ok ? extractFields(parsedSchema.value) : []

  function localProblem(): string | null {
    if (drafts.title.trim() === '') return 'A title is required.'
    if (drafts.category === '') return 'A category is required.'
    if (form === null && drafts.document_type === '') return 'A document type is required.'
    if (!parsedSchema.ok) return `Schema must be valid JSON: ${parsedSchema.message}`
    // Only the wire SHAPE is checked here — fields[].key/label/type present
    // and typed, options/source_form/display_key typed when given. Business
    // rules (a `select` needs `options`, `source_form` names a real form,
    // keys are unique) stay server-only: duplicating apps/process/schemas.py's
    // real validator here would drift out of sync with it, so those stay
    // 422s, not local refusals.
    if (!isFormSchemaSpec(parsedSchema.value)) {
      return 'Schema must have the shape { fields: [{ key, label, type, ... }] }.'
    }
    return null
  }

  function buildPatch(current: Drafts, existing: FormOut, schema: FormSchemaSpec): FormUpdateIn {
    const patch: FormUpdateIn = {}
    if (current.title.trim() !== existing.title) patch.title = current.title.trim()
    if (textOrNull(current.document_number) !== existing.document_number) {
      patch.document_number = textOrNull(current.document_number)
    }
    if (current.category !== existing.category) patch.category = requireCategory(current.category)
    const tags = tagsFromText(current.tags)
    if (JSON.stringify(tags) !== JSON.stringify(existing.tags)) patch.tags = tags
    if (current.schemaText !== JSON.stringify(existing.form_schema, null, 2)) {
      patch.form_schema = schema
    }
    if (current.status !== existing.status) patch.status = requireFormStatus(current.status)
    return patch
  }

  async function save(): Promise<void> {
    if (saving) return
    const problem = localProblem()
    if (problem !== null) {
      setValidationError(problem)
      return
    }
    // localProblem() above already refused both cases; re-checking here
    // narrows parsedSchema.value to FormSchemaSpec with no cast.
    if (!parsedSchema.ok || !isFormSchemaSpec(parsedSchema.value)) return
    setValidationError(null)
    setSaving(true)
    try {
      const schema = parsedSchema.value
      if (form === null) {
        const body: FormCreateIn = {
          title: drafts.title.trim(),
          category: requireCategory(drafts.category),
          document_type: requireDocumentType(drafts.document_type),
          form_schema: schema,
        }
        const documentNumber = textOrNull(drafts.document_number)
        if (documentNumber !== null) body.document_number = documentNumber
        const tags = tagsFromText(drafts.tags)
        if (tags.length > 0) body.tags = tags
        await createMutation.mutateAsync({ body })
      } else {
        const patch = buildPatch(drafts, form, schema)
        if (Object.keys(patch).length > 0) {
          await updateMutation.mutateAsync({ path: { form_id: form.id }, body: patch })
        }
      }
      // Query params (category, status) vary the list's cache key, so a
      // partial key here — rather than manual setQueryData — invalidates
      // every variant currently mounted.
      await queryClient.invalidateQueries({ queryKey: processFormsListQueryKey() })
      toast.success('Form saved successfully')
      onOpenChange(false)
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Could not save the form.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    // While a save is in flight the dialog must not dismiss (Esc/outside
    // click) — a completion landing after a re-open would close the wrong
    // dialog and toast out of context.
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!saving) onOpenChange(next)
      }}
    >
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{form === null ? 'New Form' : 'Edit Form'}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2">
            <TextField
              label="Title"
              automationId="FormDialog-title"
              value={drafts.title}
              onChange={(value) => setDraft('title', value)}
            />
            <TextField
              label="Document number"
              automationId="FormDialog-document-number"
              value={drafts.document_number}
              onChange={(value) => setDraft('document_number', value)}
            />
            <label className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">Category</span>
              <select
                className={INPUT_CLASS}
                value={drafts.category}
                onChange={(event) => setDraft('category', event.target.value)}
                data-automation-id="FormDialog-category"
              >
                <option value="">Select a category</option>
                {(categoriesQuery.data?.forms ?? []).map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">Document type</span>
              <select
                className={INPUT_CLASS}
                value={drafts.document_type}
                disabled={form !== null}
                onChange={(event) => setDraft('document_type', event.target.value)}
                data-automation-id="FormDialog-document-type"
              >
                <option value="">Select a type</option>
                <option value="form">Form</option>
                <option value="register">Register</option>
              </select>
              {form !== null && (
                <span className="text-xs font-normal text-slate-500">
                  Fixed once a form is created.
                </span>
              )}
            </label>
            <label className="flex flex-col gap-1 text-sm font-medium md:col-span-2">
              <span className="text-slate-700">Tags</span>
              <input
                type="text"
                className={INPUT_CLASS}
                value={drafts.tags}
                placeholder="comma, separated, tags"
                onChange={(event) => setDraft('tags', event.target.value)}
                data-automation-id="FormDialog-tags"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">Schema (JSON)</span>
              <textarea
                className={`${INPUT_CLASS} min-h-64 font-mono text-xs`}
                value={drafts.schemaText}
                aria-invalid={!parsedSchema.ok}
                onChange={(event) => setDraft('schemaText', event.target.value)}
                data-automation-id="FormDialog-schema"
              />
              {!parsedSchema.ok && (
                <p className="text-xs text-red-700" data-automation-id="FormDialog-schema-error">
                  {parsedSchema.message}
                </p>
              )}
            </label>
            <div className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-slate-700">Preview</span>
              {/* The real EntryForm, disabled — what a staff member sees
                  filling this form, not a schema editor's guess at it. */}
              <div
                className="flex min-h-64 flex-col gap-2 overflow-y-auto rounded-md border border-slate-200 p-3"
                data-automation-id="FormDialog-preview"
              >
                {!parsedSchema.ok ? (
                  <span className="text-xs font-normal text-slate-500">
                    Fix the JSON to preview fields.
                  </span>
                ) : previewFields.length === 0 ? (
                  <span className="text-xs font-normal text-slate-500">No fields yet.</span>
                ) : (
                  <EntryForm
                    schema={previewFields}
                    staffOptions={[]}
                    submitting={false}
                    automationIdPrefix="FormDialog-preview-entry"
                    disabled
                    onSubmit={() => {
                      throw new Error('The disabled preview form must never submit.')
                    }}
                  />
                )}
              </div>
            </div>
          </div>

          {validationError && (
            <p
              role="alert"
              className="text-sm text-red-700"
              data-automation-id="FormDialog-validation"
            >
              {validationError}
            </p>
          )}
        </div>

        <DialogFooter className={form !== null ? 'sm:justify-between' : undefined}>
          {/* Archiving replaces delete (apps/process/api.py: "there is
              deliberately no DELETE route on forms"), so this is the only
              archive control there is — create mode has no existing row to
              archive, and the create endpoint has no status field. */}
          {form !== null && (
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300"
                checked={drafts.status === 'archived'}
                onChange={(event) =>
                  setDraft('status', event.target.checked ? 'archived' : 'active')
                }
                data-automation-id="FormDialog-archived"
              />
              <span className="text-slate-700">Archived</span>
            </label>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => onOpenChange(false)}
              data-automation-id="FormDialog-cancel"
            >
              Cancel
            </Button>
            <Button
              disabled={saving}
              onClick={() => void save()}
              data-automation-id="FormDialog-submit"
            >
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TextField({
  label,
  automationId,
  value,
  onChange,
}: {
  label: string
  automationId: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium">
      <span className="text-slate-700">{label}</span>
      <input
        type="text"
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-automation-id={automationId}
      />
    </label>
  )
}
