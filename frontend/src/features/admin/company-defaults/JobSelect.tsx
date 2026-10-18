import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { jobJobsOptionsListOptions } from '@/api'
import { JobPicker } from '@/features/shared/JobPicker'

import { fieldAutomationId } from './fieldAutomationId'
import type { SettingsFieldControlProps } from './SettingsFieldInput'

/**
 * A setting that names one of the shop's internal jobs, such as the General
 * work job the office sweeps clocked time onto (KAN-380). Offers the special
 * jobs through the shared picker and the admin job list, as leave settings do.
 */
export function JobSelect({ field, value, onChange, section }: SettingsFieldControlProps) {
  const { t } = useTranslation('admin')
  const jobsQuery = useQuery(jobJobsOptionsListOptions({ query: { status: 'special' } }))
  const automationId = fieldAutomationId(section, field.key)

  if (jobsQuery.isError) {
    return (
      <p className="text-xs text-red-700" data-automation-id={`${automationId}-error`}>
        {t('jobSelect.loadFailed')}
      </p>
    )
  }

  const jobs = jobsQuery.data?.jobs ?? []
  return (
    <JobPicker
      automationIdPrefix={automationId}
      ariaLabel={field.label}
      jobs={jobs}
      selected={jobs.find((job) => job.id === value) ?? null}
      disabled={field.read_only}
      loading={jobsQuery.isPending}
      placeholder={t('jobSelect.placeholder')}
      triggerLabel={(job) => job?.name ?? ''}
      typedSearchLimit={null}
      commitOnTab={false}
      onSelect={(job) => onChange(job.id)}
    />
  )
}
