import type { SettingsFieldOut } from '@/api'
import { INPUT_CLASS } from '@/components/ui/field'

import { BrandingThemeSelect } from './BrandingThemeSelect'
import { CompanySelect } from './CompanySelect'
import { fieldAutomationId } from './fieldAutomationId'
import { LogoField } from './LogoField'
import { fromDateTimeLocalInput, toDateTimeLocalInput, type FieldValue } from './snapshot'

// A sanctioned field-name exception, alongside the working-hours grid and the
// logo/logo_wide keys (logoAspectRatio.ts's LOGO_ASPECT_RULES and LogoField's
// requireLogoFieldName both key on them too, so a new image slot forces a
// frontend touch there regardless — the backend LogoFieldName Literal already
// closes that union) (Decision 6): the quote-terms textarea gets a character
// counter, a blank warning and a link out to Xero, none of which the schema
// can describe.
const XERO_QUOTE_TERMS_KEY = 'xero_quote_terms'
const XERO_QUOTE_TERMS_MAX_LENGTH = 4000
const XERO_QUOTE_TERMS_WARNING_LENGTH = 3600
const XERO_INVOICE_SETTINGS_URL = 'https://go.xero.com/InvoiceSettings/InvoiceSettings.aspx'

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

export function SettingsFieldInput({ field, value, onChange, section }: SettingsFieldInputProps) {
  const automationId = fieldAutomationId(section, field.key)

  // Special-type branches precede the generic INPUT_TYPE lookup: each one
  // narrows field.type away from GenericFieldType, so moving one below the
  // lookup would break the exhaustiveness check above.
  if (field.type === 'company') {
    return <CompanySelect field={field} value={value} onChange={onChange} section={section} />
  }

  if (field.type === 'xero_branding_theme') {
    return <BrandingThemeSelect field={field} value={value} onChange={onChange} section={section} />
  }

  if (field.type === 'image') {
    return <LogoField field={field} value={value} onChange={onChange} section={section} />
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
    const stringValue = value === null ? '' : String(value)

    if (field.key === XERO_QUOTE_TERMS_KEY) {
      const count = stringValue.length
      const isBlank = stringValue.trim().length === 0
      return (
        <div className="flex flex-col gap-2">
          <textarea
            className={`${INPUT_CLASS} min-h-40`}
            value={stringValue}
            readOnly={field.read_only}
            onChange={(event) => onChange(event.target.value)}
            maxLength={XERO_QUOTE_TERMS_MAX_LENGTH}
            aria-invalid={isBlank}
            aria-label={field.label}
            data-automation-id={automationId}
          />
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <a
              href={XERO_INVOICE_SETTINGS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-indigo-600 hover:underline"
            >
              Open Xero Invoice Settings
            </a>
            <span
              className={
                count >= XERO_QUOTE_TERMS_WARNING_LENGTH
                  ? 'shrink-0 tabular-nums text-amber-700'
                  : 'shrink-0 tabular-nums text-slate-500'
              }
              data-automation-id={`${automationId}-count`}
            >
              {count.toLocaleString()} / {XERO_QUOTE_TERMS_MAX_LENGTH.toLocaleString()} characters
            </span>
          </div>
          {isBlank && (
            <p className="text-xs text-red-700">
              Enter quote terms before creating quotes in Xero.
            </p>
          )}
        </div>
      )
    }

    return (
      <textarea
        className={`${INPUT_CLASS} min-h-24`}
        value={stringValue}
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
