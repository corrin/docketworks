import type { FormFieldSchema, FormSchemaSpec } from '@/api'

// apps/process/schemas.py's FormFieldSchema.type Literal, mirrored so a
// parsed field's `type` narrows to the same closed union the wire declares.
const FIELD_TYPES = [
  'text',
  'textarea',
  'date',
  'boolean',
  'number',
  'select',
  'staff',
  'entry_ref',
] as const
type FieldType = (typeof FIELD_TYPES)[number]

function isFieldType(value: unknown): value is FieldType {
  return typeof value === 'string' && (FIELD_TYPES as readonly string[]).includes(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

/** Structural only — the wire shape TypeScript needs to read a stored
 * `form_schema` as a typed `FormFieldSchema[]`, checked field-by-field with
 * `in` so no `as` cast is needed anywhere a caller parses one. Business
 * rules (a `select` field needs `options`, `source_form` must name a real
 * form, keys must be unique) stay server-only: duplicating
 * apps/process/schemas.py's real validator here would drift out of sync
 * with it, so those stay 422s at write time, not a local re-check on read.
 *
 * The one parser for "is this object a FormFieldSchema" — FormDialog's
 * schema editor, EntryForm's callers (FormEntriesPage, LinkedEntriesDialog)
 * and the Fill dialog all read a form's `form_schema` through this, rather
 * than each carrying its own copy (ADR 0039).
 */
function isFormFieldSchema(value: unknown): value is FormFieldSchema {
  if (typeof value !== 'object' || value === null) return false
  if (!('key' in value) || typeof value.key !== 'string') return false
  if (!('label' in value) || typeof value.label !== 'string') return false
  if (!('type' in value) || !isFieldType(value.type)) return false
  if ('required' in value && value.required !== undefined && typeof value.required !== 'boolean') {
    return false
  }
  if ('options' in value && value.options !== undefined && value.options !== null) {
    if (!isStringArray(value.options)) return false
  }
  if ('source_form' in value && value.source_form !== undefined && value.source_form !== null) {
    if (typeof value.source_form !== 'string') return false
  }
  if ('display_key' in value && value.display_key !== undefined && value.display_key !== null) {
    if (typeof value.display_key !== 'string') return false
  }
  return true
}

export function isFormSchemaSpec(value: unknown): value is FormSchemaSpec {
  return (
    typeof value === 'object' &&
    value !== null &&
    'fields' in value &&
    Array.isArray(value.fields) &&
    value.fields.every(isFormFieldSchema)
  )
}

/** A form's fields, or an empty list for anything not fully shaped
    `{ fields: [...] }` — a schema mid-edit is expected to be momentarily
    unrecognisable (FormDialog's live preview), and a form with no schema
    yet is a real, valid state (FormEntriesPage's "no fields" message). */
export function extractFields(value: unknown): FormFieldSchema[] {
  return isFormSchemaSpec(value) ? value.fields : []
}
