import { useQuery } from '@tanstack/react-query'

import { isApiErrorStatus, xeroBrandingThemesListOptions } from '@/api'
import { INPUT_CLASS } from '@/components/ui/field'

import type { SettingsFieldInputProps } from './SettingsFieldInput'

const NOT_CONNECTED_MESSAGE = 'Xero is not connected.'
const LOAD_FAILED_MESSAGE = 'Could not load branding themes from Xero.'
const EMPTY_MESSAGE = 'No branding themes are available in the connected Xero organisation.'
const SETUP_INCOMPLETE_LABEL = 'Xero setup incomplete — select a branding theme'

const DISABLED_SELECT_CLASS = `${INPUT_CLASS} bg-slate-100 text-slate-500`

/**
 * Ported from v1 SectionForm.vue:170-218,625-673 — four states over the Xero
 * branding-themes endpoint, plus v1's "never write null back" rule: once a
 * theme id is set, selecting a theme completes Xero setup, so an empty
 * selection is ignored rather than clearing the field.
 */
export function BrandingThemeSelect({ field, value, onChange, section }: SettingsFieldInputProps) {
  const automationId = `CompanyDefaultsPage-${section}-field-${field.key}`
  // The endpoint's 401 means "Xero is not connected", a state to render, not
  // recover from by retrying — retry:false keeps that render immediate.
  const themesQuery = useQuery({ ...xeroBrandingThemesListOptions(), retry: false })
  const selected = typeof value === 'string' ? value : ''

  if (themesQuery.isPending) {
    return (
      <select
        className={DISABLED_SELECT_CLASS}
        value=""
        disabled
        aria-label={field.label}
        data-automation-id={automationId}
      >
        <option value="">Loading Xero branding themes…</option>
      </select>
    )
  }

  if (themesQuery.isError) {
    const message = isApiErrorStatus(themesQuery.error, 401)
      ? NOT_CONNECTED_MESSAGE
      : LOAD_FAILED_MESSAGE
    return (
      <div className="flex flex-col gap-1">
        <select
          className={DISABLED_SELECT_CLASS}
          value=""
          disabled
          aria-label={field.label}
          data-automation-id={automationId}
        >
          <option value="">{message}</option>
        </select>
        <p className="text-xs text-red-700" data-automation-id={`${automationId}-error`}>
          {message}
        </p>
      </div>
    )
  }

  const themes = themesQuery.data
  if (themes.length === 0) {
    return (
      <div className="flex flex-col gap-1">
        <select
          className={DISABLED_SELECT_CLASS}
          value=""
          disabled
          aria-label={field.label}
          data-automation-id={automationId}
        >
          <option value="">{EMPTY_MESSAGE}</option>
        </select>
        <p className="text-xs text-amber-700" data-automation-id={`${automationId}-empty`}>
          {EMPTY_MESSAGE}
        </p>
      </div>
    )
  }

  // A stale id from a theme deleted in Xero is never silently dropped: it
  // stays selected and visible until the admin explicitly picks another.
  const isKnown = selected !== '' && themes.some((theme) => theme.external_id === selected)
  const isUnavailable = selected !== '' && !isKnown

  return (
    <select
      className={INPUT_CLASS}
      value={selected}
      disabled={field.read_only}
      onChange={(event) => {
        const next = event.target.value
        if (next === '') return // v1 rule: an empty selection is never written back.
        onChange(next)
      }}
      aria-label={field.label}
      data-automation-id={automationId}
    >
      {selected === '' && (
        <option value="" disabled>
          {SETUP_INCOMPLETE_LABEL}
        </option>
      )}
      {isUnavailable && <option value={selected}>Unavailable theme ({selected})</option>}
      {themes.map((theme) => (
        <option key={theme.external_id} value={theme.external_id}>
          {theme.name}
          {theme.is_default ? ' (Xero default)' : ''}
        </option>
      ))}
    </select>
  )
}
