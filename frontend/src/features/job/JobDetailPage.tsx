import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { FileText, Printer } from 'lucide-react'
import { toast } from 'sonner'

import { apiErrorMessage, getFullJobOptions, jobJobsStatusValuesRetrieveOptions } from '@/api'
import { InlineEditSelect } from '@/components/InlineEditSelect'
import { InlineEditText } from '@/components/InlineEditText'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { lazy, Suspense } from 'react'

import type { JobFieldValues } from './delta'
import { JobAttachmentsTab } from './JobAttachmentsTab'
import { JobSettingsTab } from './JobSettingsTab'
import { JobViewTabs } from './JobViewTabs'
import { printDeliveryDocket, printWorkshopPdf } from './print'
import type { JobTabKey } from './tabs'
import { useJobFieldSave } from './useJobFieldSave'

// Lazy: the finish tab drags the invoice card, dialog, and comparison table
// with it; jobs are usually opened to edit settings or costs, not to finish.
const JobFinishTab = lazy(() =>
  import('./JobFinishTab').then((module) => ({ default: module.JobFinishTab })),
)
// Lazy: the quote tab carries the whole cost-line grid and item picker.
const JobQuoteTab = lazy(() =>
  import('./costing/JobQuoteTab').then((module) => ({ default: module.JobQuoteTab })),
)
const JobEstimateTab = lazy(() =>
  import('./costing/JobEstimateTab').then((module) => ({ default: module.JobEstimateTab })),
)

const PRICING_OPTIONS = [
  { key: 'fixed_price', label: 'Fixed Price' },
  { key: 'time_materials', label: 'Time & Materials' },
]

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
  const statusValues = useQuery(jobJobsStatusValuesRetrieveOptions())
  const { save } = useJobFieldSave(jobId)

  const saveField = (baseline: JobFieldValues, changes: JobFieldValues) => {
    save(baseline, changes).catch((error: unknown) => {
      // The concurrency interceptor already toasts 412/428 with a Retry.
      if (!isConcurrencyError(error)) {
        toast.error(apiErrorMessage(error, 'Failed to save the job.'))
      }
    })
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-200 p-4">
        <div className="flex items-center gap-2">
          <span data-automation-id="JobView-job-number" className="text-xl font-bold text-gray-900">
            Job #{job.job_number} -
          </span>
          <InlineEditText
            value={job.name}
            required
            displayClassName="text-xl font-bold text-gray-900"
            onCommit={(name) => saveField({ name: job.name }, { name })}
          />
          {/* The editor renders only once real choices exist: an empty
              dropdown over a raw wire key would be a silent read failure. */}
          {statusValues.isSuccess ? (
            <InlineEditSelect
              automationId="JobView-status"
              value={job.job_status}
              options={Object.entries(statusValues.data.statuses).map(([key, label]) => ({
                key,
                label,
              }))}
              onCommit={(job_status) => saveField({ job_status: job.job_status }, { job_status })}
            />
          ) : statusValues.isError ? (
            <span className="text-sm text-red-600">Status choices failed to load</span>
          ) : null}
          <InlineEditSelect
            automationId="JobView-pricing-method"
            value={job.pricing_methodology}
            options={PRICING_OPTIONS}
            onCommit={(pricing_methodology) =>
              saveField({ pricing_methodology: job.pricing_methodology }, { pricing_methodology })
            }
          />
        </div>
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

      {/* Keyed by job: both tabs hydrate local state once per mount, and
          navigating to another job must remount them, not leak the old
          job's values. */}
      {activeTab === 'jobSettings' ? (
        <JobSettingsTab key={jobId} jobId={jobId} job={job} />
      ) : activeTab === 'attachments' ? (
        <JobAttachmentsTab key={jobId} jobId={jobId} />
      ) : activeTab === 'finishJob' ? (
        <Suspense fallback={<div className="p-6 text-sm text-gray-500">Loading…</div>}>
          <JobFinishTab key={jobId} jobId={jobId} job={job} />
        </Suspense>
      ) : activeTab === 'quote' ? (
        <Suspense fallback={<div className="p-6 text-sm text-gray-500">Loading…</div>}>
          <JobQuoteTab key={jobId} jobId={jobId} job={job} />
        </Suspense>
      ) : activeTab === 'estimate' ? (
        <Suspense fallback={<div className="p-6 text-sm text-gray-500">Loading…</div>}>
          <JobEstimateTab key={jobId} jobId={jobId} />
        </Suspense>
      ) : (
        <div className="p-6 text-sm text-gray-500">This tab ships in a later slice.</div>
      )}
    </div>
  )
}
