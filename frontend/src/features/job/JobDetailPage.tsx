import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { FileText, Printer, XCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { apiErrorMessage, getFullJobOptions, jobJobsStatusValuesRetrieveOptions } from '@/api'
import { Button } from '@/components/ui/button'
import { InlineEditSelect } from '@/components/InlineEditSelect'
import { InlineEditText } from '@/components/InlineEditText'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { lazy, Suspense } from 'react'

import type { JobFieldValues } from './delta'
import { JobAttachmentsTab } from './JobAttachmentsTab'
import { JobSettingsTab } from './JobSettingsTab'
import { JobRejectionAction } from './JobRejectionAction'
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
const JobActualTab = lazy(() =>
  import('./costing/JobActualTab').then((module) => ({ default: module.JobActualTab })),
)
// Lazy: a static import was rejected because it would put PhoneCallTable,
// JobPicker and the link dialog into this page's initial chunk for every
// visitor, most of whom never open History.
const JobHistoryTab = lazy(() =>
  import('./JobHistoryTab').then((module) => ({ default: module.JobHistoryTab })),
)

const JobQuotingChatTab = lazy(() =>
  import('./JobQuotingChatTab').then((module) => ({ default: module.JobQuotingChatTab })),
)

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
  const { t } = useTranslation('job')
  const jobQuery = useSuspenseQuery(getFullJobOptions({ path: { job_id: jobId } }))
  const job = jobQuery.data.data.job
  const statusValues = useQuery(jobJobsStatusValuesRetrieveOptions())
  const { save } = useJobFieldSave(jobId)

  const saveField = (baseline: JobFieldValues, changes: JobFieldValues) => {
    save(baseline, changes).catch((error: unknown) => {
      // The concurrency interceptor already toasts 412/428 with a Retry.
      if (!isConcurrencyError(error)) {
        toast.error(apiErrorMessage(error, t('detailPage.saveFailed')))
      }
    })
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex flex-shrink-0 flex-wrap items-center justify-between gap-3 border-b border-gray-200 p-4">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span data-automation-id="JobView-job-number" className="text-xl font-bold text-gray-900">
            {t('detailPage.jobNumber', { jobNumber: job.job_number })}
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
            <span className="text-sm text-red-600">{t('detailPage.statusChoicesFailed')}</span>
          ) : null}
          <InlineEditSelect
            automationId="JobView-pricing-method"
            value={job.pricing_methodology}
            options={[
              { key: 'fixed_price', label: t('detailPage.pricing.fixedPrice') },
              { key: 'time_materials', label: t('detailPage.pricing.timeMaterials') },
            ]}
            onCommit={(pricing_methodology) =>
              saveField({ pricing_methodology: job.pricing_methodology }, { pricing_methodology })
            }
          />
          {job.rejected_flag && (
            <span
              data-automation-id="JobView-rejected-badge"
              className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-1 text-xs font-medium text-red-700"
            >
              <XCircle className="h-4 w-4" aria-hidden="true" />
              {t('detailPage.rejected')}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <JobRejectionAction key={jobId} job={job} />
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-automation-id="JobView-print-workshop-pdf"
            onClick={() => {
              void printWorkshopPdf(jobId)
            }}
          >
            <Printer className="h-4 w-4" />
            {t('detailPage.workshopPdf')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-automation-id="JobView-print-delivery-docket"
            onClick={() => {
              void printDeliveryDocket(jobId)
            }}
          >
            <FileText className="h-4 w-4" />
            {t('detailPage.deliveryDocket')}
          </Button>
        </div>
      </div>

      <JobViewTabs
        activeTab={activeTab}
        pricingMethodology={job.pricing_methodology}
        onChangeTab={onChangeTab}
      />

      <div id="JobViewTabs-panel" role="tabpanel" aria-labelledby={`JobViewTabs-${activeTab}`}>
        {/* Keyed by job: both tabs hydrate local state once per mount, and
          navigating to another job must remount them, not leak the old
          job's values. */}
        {activeTab === 'jobSettings' ? (
          <JobSettingsTab key={jobId} jobId={jobId} job={job} />
        ) : activeTab === 'attachments' ? (
          <JobAttachmentsTab key={jobId} jobId={jobId} />
        ) : activeTab === 'finishJob' ? (
          <Suspense
            fallback={<div className="p-6 text-sm text-gray-500">{t('detailPage.loading')}</div>}
          >
            <JobFinishTab key={jobId} jobId={jobId} job={job} />
          </Suspense>
        ) : activeTab === 'quote' ? (
          <Suspense
            fallback={<div className="p-6 text-sm text-gray-500">{t('detailPage.loading')}</div>}
          >
            <JobQuoteTab key={jobId} jobId={jobId} job={job} />
          </Suspense>
        ) : activeTab === 'estimate' ? (
          <Suspense
            fallback={<div className="p-6 text-sm text-gray-500">{t('detailPage.loading')}</div>}
          >
            <JobEstimateTab key={jobId} jobId={jobId} />
          </Suspense>
        ) : activeTab === 'actual' ? (
          <Suspense
            fallback={<div className="p-6 text-sm text-gray-500">{t('detailPage.loading')}</div>}
          >
            <JobActualTab key={jobId} jobId={jobId} />
          </Suspense>
        ) : activeTab === 'quotingChat' ? (
          <Suspense
            fallback={<div className="p-6 text-sm text-gray-500">{t('detailPage.loading')}</div>}
          >
            <JobQuotingChatTab key={jobId} jobId={jobId} />
          </Suspense>
        ) : activeTab === 'history' ? (
          <Suspense
            fallback={<div className="p-6 text-sm text-gray-500">{t('detailPage.loading')}</div>}
          >
            <JobHistoryTab key={jobId} jobId={jobId} />
          </Suspense>
        ) : (
          <div className="p-6 text-sm text-gray-500">{t('detailPage.laterSlice')}</div>
        )}
      </div>
    </div>
  )
}
