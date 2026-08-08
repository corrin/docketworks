import { useSuspenseQuery } from '@tanstack/react-query'
import { FileText, Printer } from 'lucide-react'

import { getFullJobOptions } from '@/api'
import { JobSettingsTab } from './JobSettingsTab'
import { JobViewTabs } from './JobViewTabs'
import { printDeliveryDocket, printWorkshopPdf } from './print'
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
      <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-200 p-4">
        <h1 className="text-xl font-bold text-gray-900">
          Job #{job.job_number} — {job.name}
        </h1>
        <div className="flex space-x-2">
          <button
            type="button"
            data-automation-id="JobView-print-workshop-pdf"
            className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50"
            onClick={() => {
              void printWorkshopPdf(jobId)
            }}
          >
            <Printer className="mr-1 h-4 w-4" />
            Workshop PDF
          </button>
          <button
            type="button"
            data-automation-id="JobView-print-delivery-docket"
            className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1.5 text-sm transition-colors hover:bg-gray-50"
            onClick={() => {
              void printDeliveryDocket(jobId)
            }}
          >
            <FileText className="mr-1 h-4 w-4" />
            Delivery Docket
          </button>
        </div>
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
