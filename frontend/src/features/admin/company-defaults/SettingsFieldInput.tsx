import type { SettingsFieldOut } from '@/api'
import { INPUT_CLASS } from '@/components/ui/field'

import { fromDateTimeLocalInput, toDateTimeLocalInput, type FieldValue } from './snapshot'

export interface SettingsFieldInputProps {
  field: SettingsFieldOut
  value: FieldValue
  onChange: (value: FieldValue) => void
  section: string
}

// Total over the widget types the generic branch serves: when the backend grows
// a new SettingsFieldType the generated union grows and this Record stops
// type-checking — a silent fall-through to a text input is the failure mode the
// exhaustiveness buys out (Decision 6).
type GenericFieldType = Exclude<
  SettingsFieldOut['type'],
  'boolean' | 'textarea' | 'company' | 'xero_branding_theme' | 'image'
>
const INPUT_TYPE: Record<GenericFieldType, string> = {
  email: 'email',
  url: 'url',
  number: 'number',
  time: 'time',
  date: 'date',
  datetime: 'datetime-local',
  text: 'text',
}

/** Placeholder for the three widgets Task 5 owns (company picker, Xero branding
 *  theme select, logo uploader). Shows the stored value uneditably rather than
 *  hiding the field: a section that silently omits a configured setting reads as
 *  data loss to the admin looking for it. */
function PendingWidget({
  field,
  value,
  automationId,
}: {
  field: SettingsFieldOut
  value: FieldValue
  automationId: string
}) {
  return (
    <input
      type="text"
      className={`${INPUT_CLASS} bg-slate-100 text-slate-500`}
      value={value === null ? '' : String(value)}
      readOnly
      disabled
      aria-label={field.label}
      data-automation-id={automationId}
    />
  )
}

export function SettingsFieldInput({ field, value, onChange, section }: SettingsFieldInputProps) {
  const automationId = `CompanyDefaultsPage-${section}-field-${field.key}`

  if (field.type === 'company') {
    return <PendingWidget field={field} value={value} automationId={automationId} />
  }

  if (field.type === 'xero_branding_theme') {
    return <PendingWidget field={field} value={value} automationId={automationId} />
  }

  if (field.type === 'image') {
    return <PendingWidget field={field} value={value} automationId={automationId} />
  }

  if (field.type === 'boolean') {
    return (
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300"
        checked={value === true}
        disabled={field.read_only}
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
        value={value === null ? '' : String(value)}
        readOnly={field.read_only}
        onChange={(event) => onChange(event.target.value)}
        aria-label={field.label}
        data-automation-id={automationId}
      />
    )
  }

  // `datetime-local` speaks local wall-clock with no offset while the wire
  // carries a UTC instant, so this widget alone translates in both directions.
  // The snapshot stores the same minute-precision instant, so an untouched
  // field stays clean (proved in snapshot.test.ts).
  const isDateTime = field.type === 'datetime'
  const displayed =
    value === null ? '' : isDateTime ? toDateTimeLocalInput(String(value)) : String(value)
  const handleChange = (raw: string): void => {
    if (!isDateTime) {
      onChange(raw)
      return
    }
    // A cleared picker is an unset timestamp; '' would 422 (ADR 0040).
    onChange(raw === '' ? null : fromDateTimeLocalInput(raw))
  }

  // text / email / url / number / time / date / datetime all render as a typed
  // <input>. Values stay wire strings (Decimals are strings on the wire; the
  // form never reformats a number it isn't editing — ADR 0046).
  return (
    <input
      type={INPUT_TYPE[field.type]}
      step={field.type === 'number' ? 'any' : undefined}
      className={`${INPUT_CLASS} ${field.read_only ? 'bg-slate-100 text-slate-500' : ''}`}
      value={displayed}
      readOnly={field.read_only}
      onChange={(event) => handleChange(event.target.value)}
      aria-label={field.label}
      data-automation-id={automationId}
    />
  )
}
