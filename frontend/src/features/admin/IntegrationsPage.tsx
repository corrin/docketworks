import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  integrationSettingsPartialUpdateMutation,
  integrationSettingsRetrieveOptions,
  integrationSettingsRetrieveQueryKey,
  type IntegrationSettingsOut,
  type IntegrationSettingsPatchIn,
} from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { QueryState } from '@/features/shared/QueryState'
import { useUnsavedChangesGuard } from '@/features/shared/useUnsavedChangesGuard'

/**
 * The install's credentials for external services (ADR 0053): one section per
 * integration, one row behind them all. Secrets never come back from the
 * server — the response says only whether one is stored — so a secret's draft
 * is a pending instruction rather than an edit of a loaded value: `undefined`
 * leaves it alone, a string replaces it, `null` clears it.
 */
type SecretDraft = string | null | undefined

type SecretKey = 'google_maps_api_key' | 'phone_provider_username' | 'phone_provider_password'
type PlainKey = 'phone_provider_base_url' | 'phone_provider_account_code'
type FlagKey = 'phone_provider_enabled' | 'phone_provider_recording_deletion_enabled'

const SECRET_KEYS: readonly SecretKey[] = [
  'google_maps_api_key',
  'phone_provider_username',
  'phone_provider_password',
]
const PLAIN_KEYS: readonly PlainKey[] = ['phone_provider_base_url', 'phone_provider_account_code']
const FLAG_KEYS: readonly FlagKey[] = [
  'phone_provider_enabled',
  'phone_provider_recording_deletion_enabled',
]

type Drafts = Record<SecretKey, SecretDraft> & Record<PlainKey, string> & Record<FlagKey, boolean>

function snapshot(settings: IntegrationSettingsOut): Drafts {
  return {
    google_maps_api_key: undefined,
    phone_provider_username: undefined,
    phone_provider_password: undefined,
    phone_provider_base_url: settings.phone_provider_base_url ?? '',
    phone_provider_account_code: settings.phone_provider_account_code ?? '',
    phone_provider_enabled: settings.phone_provider_enabled,
    phone_provider_recording_deletion_enabled: settings.phone_provider_recording_deletion_enabled,
  }
}

/** Dirty fields only — exclude_unset is the wire contract, so an untouched
 * field must not appear at all. A cleared text box means unset (ADR 0040). */
function buildPatch(drafts: Drafts, server: Drafts): IntegrationSettingsPatchIn {
  const patch: IntegrationSettingsPatchIn = {}
  for (const key of FLAG_KEYS) {
    if (drafts[key] !== server[key]) patch[key] = drafts[key]
  }
  // Trimmed on the way out: the server strips before its not-blank check, so a
  // whitespace-only box is "unset" here too rather than a 422.
  for (const key of PLAIN_KEYS) {
    const draft = drafts[key].trim()
    if (draft !== server[key]) patch[key] = draft === '' ? null : draft
  }
  for (const key of SECRET_KEYS) {
    const draft = drafts[key]
    if (draft === undefined) continue
    if (draft === null) {
      patch[key] = null
    } else if (draft.trim() !== '') {
      patch[key] = draft.trim()
    }
  }
  return patch
}

const fieldId = (section: string, key: string): string => `IntegrationsPage-${section}-field-${key}`

export function IntegrationsPage() {
  const settingsQuery = useQuery(integrationSettingsRetrieveOptions())

  return (
    <div
      className="mx-auto flex max-w-3xl flex-col gap-6 p-6"
      data-automation-id="IntegrationsPage-root"
    >
      <h1 className="text-2xl font-semibold">Integrations</h1>
      <p className="text-sm text-slate-600">
        How this installation reaches external services. Stored values are never shown again; enter
        a new one to replace it, or clear it.
      </p>
      <QueryState
        isPending={settingsQuery.isPending}
        isError={settingsQuery.isError}
        onRetry={() => void settingsQuery.refetch()}
        loadingLabel="integration settings"
        errorLabel="integration settings"
      >
        {settingsQuery.data && <SettingsForm settings={settingsQuery.data} />}
      </QueryState>
    </div>
  )
}

function SettingsForm({ settings }: { settings: IntegrationSettingsOut }) {
  const queryClient = useQueryClient()
  const updateMutation = useMutation(integrationSettingsPartialUpdateMutation())
  // Two snapshots, seeded once and advanced together only on a successful
  // save — the same discipline as CompanyDefaultsPage, for the same reason: a
  // background refetch must not wipe what the admin has typed.
  const [server, setServer] = useState<Drafts>(() => snapshot(settings))
  const [drafts, setDrafts] = useState<Drafts>(() => snapshot(settings))
  // The has_* flags are the one thing read live from the server snapshot:
  // they are status, not an edit, and the PATCH response advances them.
  const [stored, setStored] = useState<IntegrationSettingsOut>(settings)
  const [saving, setSaving] = useState(false)

  const patch = useMemo(() => buildPatch(drafts, server), [drafts, server])
  const isDirty = Object.keys(patch).length > 0

  useUnsavedChangesGuard(isDirty)

  const setDraft = <K extends keyof Drafts>(key: K, value: Drafts[K]): void => {
    setDrafts((previous) => ({ ...previous, [key]: value }))
  }

  async function save(): Promise<void> {
    if (saving) return
    setSaving(true)
    try {
      const fresh = await updateMutation.mutateAsync({ body: patch })
      queryClient.setQueryData(integrationSettingsRetrieveQueryKey(), fresh)
      setStored(fresh)
      setServer(snapshot(fresh))
      setDrafts(snapshot(fresh))
      toast.success('Integrations saved')
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Could not save integration settings.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Section
        sectionKey="google"
        title="Google"
        description="Address validation for pickup addresses and company geocoding (Google Address Validation API)."
      >
        <SecretField
          section="google"
          fieldKey="google_maps_api_key"
          label="Maps API key"
          configured={stored.has_google_maps_api_key}
          draft={drafts.google_maps_api_key}
          onChange={(value) => setDraft('google_maps_api_key', value)}
        />
      </Section>

      <Section
        sectionKey="phone"
        title="Phone provider"
        description="CRM call ingestion from the phone provider's portal."
      >
        <FlagField
          section="phone"
          fieldKey="phone_provider_enabled"
          label="Enabled"
          checked={drafts.phone_provider_enabled}
          onChange={(value) => setDraft('phone_provider_enabled', value)}
        />
        <TextField
          section="phone"
          fieldKey="phone_provider_base_url"
          label="Portal URL"
          type="url"
          value={drafts.phone_provider_base_url}
          onChange={(value) => setDraft('phone_provider_base_url', value)}
        />
        <TextField
          section="phone"
          fieldKey="phone_provider_account_code"
          label="Account code"
          type="text"
          value={drafts.phone_provider_account_code}
          onChange={(value) => setDraft('phone_provider_account_code', value)}
        />
        <SecretField
          section="phone"
          fieldKey="phone_provider_username"
          label="Username"
          inputType="text"
          configured={stored.has_phone_provider_username}
          draft={drafts.phone_provider_username}
          onChange={(value) => setDraft('phone_provider_username', value)}
        />
        <SecretField
          section="phone"
          fieldKey="phone_provider_password"
          label="Password"
          configured={stored.has_phone_provider_password}
          draft={drafts.phone_provider_password}
          onChange={(value) => setDraft('phone_provider_password', value)}
        />
        <FlagField
          section="phone"
          fieldKey="phone_provider_recording_deletion_enabled"
          label="Delete archived recordings from the provider"
          checked={drafts.phone_provider_recording_deletion_enabled}
          onChange={(value) => setDraft('phone_provider_recording_deletion_enabled', value)}
        />
      </Section>

      <div
        className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-200 bg-white/95 py-3"
        data-automation-id="IntegrationsPage-footer"
      >
        <Button
          variant="outline"
          disabled={saving || !isDirty}
          onClick={() => setDrafts(server)}
          data-automation-id="IntegrationsPage-cancel-button"
        >
          Cancel
        </Button>
        <Button
          disabled={saving || !isDirty}
          onClick={() => void save()}
          data-automation-id="IntegrationsPage-save-button"
        >
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}

function Section({
  sectionKey,
  title,
  description,
  children,
}: {
  sectionKey: string
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section
      className="flex flex-col gap-4 rounded-md border border-slate-200 p-4"
      data-automation-id={`IntegrationsPage-section-${sectionKey}`}
    >
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2">{children}</div>
    </section>
  )
}

function TextField({
  section,
  fieldKey,
  label,
  type,
  value,
  onChange,
}: {
  section: string
  fieldKey: PlainKey
  label: string
  type: 'url' | 'text'
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium">
      <span className="text-slate-700">{label}</span>
      <input
        type={type}
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-automation-id={fieldId(section, fieldKey)}
      />
    </label>
  )
}

function FlagField({
  section,
  fieldKey,
  label,
  checked,
  onChange,
}: {
  section: string
  fieldKey: FlagKey
  label: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm font-medium">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        data-automation-id={fieldId(section, fieldKey)}
      />
      <span className="text-slate-700">{label}</span>
    </label>
  )
}

function secretStatus(configured: boolean, draft: SecretDraft): string {
  if (draft === null) return 'Will be cleared on save'
  if (draft !== undefined) return configured ? 'Will be replaced on save' : 'Will be set on save'
  return configured ? 'Configured' : 'Not configured'
}

function SecretField({
  section,
  fieldKey,
  label,
  inputType = 'password',
  configured,
  draft,
  onChange,
}: {
  section: string
  fieldKey: SecretKey
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
