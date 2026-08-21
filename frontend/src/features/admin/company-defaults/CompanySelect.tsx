import { useQuery } from '@tanstack/react-query'

import { companiesAllListOptions } from '@/api'
import { INPUT_CLASS } from '@/components/ui/field'

import { fieldAutomationId } from './fieldAutomationId'
import type { SettingsFieldInputProps } from './SettingsFieldInput'

/** Native `<select>` over the small companies list — matches LeaveSettingsPage's
 * raw-select house style rather than a searchable combobox, because the list
 * is short enough that scanning it beats typing into it. */
export function CompanySelect({ field, value, onChange, section }: SettingsFieldInputProps) {
  const companiesQuery = useQuery(companiesAllListOptions())
  const automationId = fieldAutomationId(section, field.key)

  if (companiesQuery.isError) {
    return (
      <p className="text-xs text-red-700" data-automation-id={`${automationId}-error`}>
        Could not load companies.
      </p>
    )
  }

  return (
    <select
      className={INPUT_CLASS}
      value={typeof value === 'string' ? value : ''}
      disabled={field.read_only || companiesQuery.isPending}
      onChange={(event) => onChange(event.target.value)}
      aria-label={field.label}
      data-automation-id={automationId}
    >
      {(companiesQuery.data ?? []).map((company) => (
        <option key={company.id} value={company.id}>
          {company.name}
        </option>
      ))}
    </select>
  )
}
