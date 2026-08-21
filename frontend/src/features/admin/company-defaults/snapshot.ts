import type { CompanyDefaultsOut, CompanyDefaultsPatchIn, SettingsFieldOut } from '@/api'

/** Every settings value is a JSON scalar by construction: the 12 widget types all
 * map scalar columns, so per-key Object.is comparison is sound where
 * LeaveSettingsPage needed a named-type field comparison (its rationale at
 * LeaveSettingsPage.tsx:45-47 does not transfer to schema-driven unknowns). */
export type FieldValue = string | number | boolean | null
export type SectionSnapshot = Record<string, FieldValue>

/** The company-defaults response, indexable by schema key. The screen's whole
 * point is that the field list arrives from the server, so the named type alone
 * cannot index it — but a bare `Record<string, unknown>` would take any object at
 * all, so the intersection keeps the wire contract while opening the dynamic read
 * (ADR 0028). One named seam here replaces an assertion at every read. */
export type CompanyDefaultsRecord = CompanyDefaultsOut & Record<string, unknown>

// The wire reads the FK as `shop_company` (schema key and GET field) but writes
// `shop_company_id` (ninja ModelSchema PatchIn). Bridged here and nowhere else.
//
// Opus: deliberately Partial where INPUT_TYPE is total. Writing under its own key
// is the rule and this bridge is the single exception, so a widget type absent
// from this map is correct by default; making it total would force every new
// widget to restate `(key) => key`. Only ninja's `_id` suffix on a ForeignKey
// earns an entry, and apps/core/settings_metadata.py has exactly one FK widget.
const WRITE_KEY_BY_TYPE: Partial<Record<SettingsFieldOut['type'], (key: string) => string>> = {
  company: (key) => `${key}_id`,
}

const isEditable = (field: SettingsFieldOut): boolean => !field.read_only && field.type !== 'image'

const pad = (value: number): string => String(value).padStart(2, '0')

/**
 * A wire instant rendered in the viewer's own zone, as `datetime-local` demands
 * (`YYYY-MM-DDTHH:MM`, no offset). Built from the local getters rather than
 * `toISOString().slice(0, 16)`, which would display UTC and shift the shown
 * time by the offset.
 */
export function toDateTimeLocalInput(wire: string): string {
  const instant = new Date(wire)
  if (Number.isNaN(instant.getTime())) {
    // Opus: a fallback here would render some other instant as if it were the
    // stored one; malformed data is fixed at the source (ADR 0015).
    throw new Error(`Company defaults carried an unparseable datetime: ${wire}`)
  }
  return (
    `${instant.getFullYear()}-${pad(instant.getMonth() + 1)}-${pad(instant.getDate())}` +
    `T${pad(instant.getHours())}:${pad(instant.getMinutes())}`
  )
}

/** The inverse: a `datetime-local` value read as local time, back on the wire as UTC. */
export function fromDateTimeLocalInput(input: string): string {
  const instant = new Date(input)
  if (Number.isNaN(instant.getTime())) {
    throw new Error(`The datetime input produced an unparseable value: ${input}`)
  }
  return instant.toISOString()
}

const normalise = (field: SettingsFieldOut, raw: unknown): FieldValue => {
  if (raw === undefined || raw === null) return null
  if (field.type === 'time' && typeof raw === 'string') return raw.slice(0, 5) // HH:MM
  // The input can only express minutes, so the snapshot holds the same
  // precision: without this a wire value carrying seconds would come back
  // truncated the moment the picker was touched and never compare clean again.
  if (field.type === 'datetime' && typeof raw === 'string') {
    return fromDateTimeLocalInput(toDateTimeLocalInput(raw))
  }
  // Integer columns arrive as wire numbers but leave the <input> as strings, so
  // both snapshots hold the string form: without this, editing an int and typing
  // the original back stayed dirty forever on Object.is('7', 7). Decimals are
  // already wire strings and pass through untouched, so '32.00' keeps its
  // trailing zeros (ADR 0046); pydantic coerces the string back on PATCH.
  if (field.type === 'number' && typeof raw === 'number') return String(raw)
  // Narrowed rather than asserted: every registered widget maps a scalar column
  // (apps/core/settings_metadata.py FIELD_TYPE_RULES), so a container here means
  // the registry grew a shape this form cannot edit and must say so.
  if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') return raw
  throw new Error(`Company defaults field ${field.key} carried a non-scalar value.`)
}

export function snapshotSection(
  defaults: CompanyDefaultsRecord,
  fields: SettingsFieldOut[],
): SectionSnapshot {
  return Object.fromEntries(
    fields.map((field) => [
      field.key,
      // An image field has no editable column of its own; the wire exposes the
      // stored file as a `<key>_url` companion, which is what the widget shows.
      field.type === 'image'
        ? normalise(field, defaults[`${field.key}_url`])
        : normalise(field, defaults[field.key]),
    ]),
  )
}

export function dirtyKeys(
  fields: SettingsFieldOut[],
  drafts: SectionSnapshot,
  server: SectionSnapshot,
): string[] {
  return fields
    .filter(isEditable)
    .map((field) => field.key)
    .filter((key) => !Object.is(drafts[key], server[key]))
}

export function buildPatch(
  fields: SettingsFieldOut[],
  drafts: SectionSnapshot,
  server: SectionSnapshot,
): CompanyDefaultsPatchIn {
  const patch: Record<string, FieldValue> = {}
  for (const field of fields.filter(isEditable)) {
    if (Object.is(drafts[field.key], server[field.key])) continue
    const writeKey = WRITE_KEY_BY_TYPE[field.type]?.(field.key) ?? field.key
    const draft = drafts[field.key]
    // Both snapshots are built from the same field list, so a dirty key the
    // drafts lack is a programming error rather than a value to coerce
    // (ADR 0015; LeaveSettingsPage.tsx:66-70 takes the same line).
    if (draft === undefined) {
      throw new Error(`The company defaults draft snapshot is missing ${field.key}.`)
    }
    // ADR 0040: a cleared box means unset; the backend refuses "" with a 422.
    patch[writeKey] = draft === '' && !field.required ? null : draft
  }
  return patch
}
