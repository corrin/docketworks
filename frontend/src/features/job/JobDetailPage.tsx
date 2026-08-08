import { useSuspenseQuery } from '@tanstack/react-query'

import { getFullJobOptions } from '@/api'
import { JobSettingsTab } from './JobSettingsTab'
import { JobViewTabs } from './JobViewTabs'
import type { JobTabKey } from './tabs'

interface JobDetailPageProps {
  jobId: string
  activeTab: JobTabKey
  onChangeTab: (tab: JobTabKey) => void
}

/**
 * Job detail shell: header line, tab bar, and the active tab's panel. Every
 * tab except jobSettings is a stub; each tab's content ships with the slice
 * that greens its specs, and must arrive lazy-loaded rather than as a static
 * import (v1 statically imported all ten tabs, dragging 3,100 untested lines
 * into this page).
 */
export function JobDetailPage({ jobId, activeTab, onChangeTab }: JobDetailPageProps) {
  const jobQuery = useSuspenseQuery(getFullJobOptions({ path: { job_id: jobId } }))
  const job = jobQuery.data.data.job

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex-shrink-0 border-b border-gray-200 p-4">
        <h1 className="text-xl font-bold text-gray-900">
          Job #{job.job_number} — {job.name}
        </h1>
      </div>

      <JobViewTabs
        activeTab={activeTab}
        pricingMethodology={job.pricing_methodology}
        onChangeTab={onChangeTab}
      />

      {activeTab === 'jobSettings' ? (
        <JobSettingsTab job={job} />
      ) : (
        <div className="p-6 text-sm text-gray-500">This tab ships in a later slice.</div>
      )}
    </div>
  )
}
