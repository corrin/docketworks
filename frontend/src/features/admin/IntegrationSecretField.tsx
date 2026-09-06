import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'

export type SecretDraft = string | null | undefined
export const fieldId = (section: string, key: string): string =>
  `IntegrationsPage-${section}-field-${key}`

function secretStatus(configured: boolean, draft: SecretDraft): string {
  if (draft === null) return 'Will be cleared on save'
  if (draft !== undefined) return configured ? 'Will be replaced on save' : 'Will be set on save'
  return configured ? 'Configured' : 'Not configured'
}

export function SecretField({
  section,
  fieldKey,
  label,
  inputType = 'password',
  configured,
  draft,
  onChange,
}: {
  section: string
  fieldKey: string
  label: string
  inputType?: 'password' | 'text'
  configured: boolean
  draft: SecretDraft
  onChange: (value: SecretDraft) => void
}) {
  const clearing = draft === null
  return (
    <div className="flex flex-col gap-1 text-sm font-medium">
      <label className="flex flex-col gap-1">
        <span className="text-slate-700">{label}</span>
        <input
          type={inputType}
          // Browsers ignore "off" on a password box and offer to save the
          // Maps key as a login; "new-password" is the value they honour.
          autoComplete="new-password"
          className={INPUT_CLASS}
          value={draft ?? ''}
          disabled={clearing}
          placeholder={configured ? 'Enter a new value to replace the stored one' : 'Not set'}
          // An emptied box is "leave it alone", never "store blank" (ADR 0040).
          onChange={(event) => onChange(event.target.value === '' ? undefined : event.target.value)}
          data-automation-id={fieldId(section, fieldKey)}
        />
      </label>
      <div className="flex items-center justify-between gap-2 text-xs font-normal text-slate-500">
        <span data-automation-id={`IntegrationsPage-${section}-status-${fieldKey}`}>
          {secretStatus(configured, draft)}
        </span>
        {configured && !clearing && (
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => onChange(null)}
            data-automation-id={`IntegrationsPage-${section}-clear-${fieldKey}`}
          >
            Clear
          </Button>
        )}
        {clearing && (
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => onChange(undefined)}
            data-automation-id={`IntegrationsPage-${section}-keep-${fieldKey}`}
          >
            Keep it
          </Button>
        )}
      </div>
    </div>
  )
}
