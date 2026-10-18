import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import {
  companiesJobsRetrieveOptions,
  jobJobsStatusChoicesRetrieveOptions,
  peopleJobsRetrieveOptions,
  type CrmJobRow,
} from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { formatCurrency, formatDate } from '@/lib/format'

/** Whose jobs the table lists. The two lists share one wire shape and one endpoint family. */
export type JobsOwner =
  { kind: 'person'; personId: string } | { kind: 'company'; companyId: string }

interface RelatedJobsTableProps {
  owner: JobsOwner
  automationId: string
  /** The company page already names the company; the person page needs the column. */
  showCompany: boolean
}

/**
 * Every job an owner (person or company) is attached to, with the sales
 * invoices on each and the invoiced total — the table both CRM detail pages
 * share (KAN-372). One row per job: a job with no invoice yet still shows,
 * because the owner wants to see every job, not only the billed ones.
 *
 * One component per owner kind owns the query, because the two generated
 * option types differ in their query-key tuple and `useQuery` will not take
 * their union; the table beneath them takes plain props and knows no query.
 */
export function RelatedJobsTable({ owner, automationId, showCompany }: RelatedJobsTableProps) {
  return owner.kind === 'person' ? (
    <PersonJobs personId={owner.personId} automationId={automationId} showCompany={showCompany} />
  ) : (
    <CompanyJobs
      companyId={owner.companyId}
      automationId={automationId}
      showCompany={showCompany}
    />
  )
}

type TableProps = Omit<RelatedJobsTableProps, 'owner'>

function PersonJobs({ personId, ...table }: TableProps & { personId: string }) {
  const jobs = useQuery(peopleJobsRetrieveOptions({ path: { person_id: personId } }))
  return (
    <JobsTable
      isPending={jobs.isPending}
      isError={jobs.isError}
      onRetry={() => void jobs.refetch()}
      rows={jobs.data?.results}
      {...table}
    />
  )
}

function CompanyJobs({ companyId, ...table }: TableProps & { companyId: string }) {
  const jobs = useQuery(companiesJobsRetrieveOptions({ path: { company_id: companyId } }))
  return (
    <JobsTable
      isPending={jobs.isPending}
      isError={jobs.isError}
      onRetry={() => void jobs.refetch()}
      rows={jobs.data?.results}
      {...table}
    />
  )
}

interface JobsTableProps extends TableProps {
  isPending: boolean
  isError: boolean
  onRetry: () => void
  rows: CrmJobRow[] | undefined
}

function JobsTable({
  isPending,
  isError,
  onRetry,
  rows,
  automationId,
  showCompany,
}: JobsTableProps) {
  const { t } = useTranslation('crm')
  // The full status vocabulary (special and archived included), the same
  // endpoint JobPicker reads: the jobs here can be in any status.
  const statuses = useQuery({ ...jobJobsStatusChoicesRetrieveOptions(), staleTime: Infinity })
  const total = rows?.reduce((sum, job) => sum + job.invoiced_total_excl_tax, 0)

  return (
    <ListTable
      isPending={isPending || statuses.isPending}
      isError={isError || statuses.isError}
      onRetry={() => {
        onRetry()
        void statuses.refetch()
      }}
      loadingLabel={t('relatedJobs.loading')}
      errorLabel={t('relatedJobs.loadFailed')}
      rows={rows}
      emptyLabel={t('relatedJobs.empty')}
      automationId={automationId}
      wrapperClassName="max-h-[32rem]"
      head={
        <tr className="border-b border-gray-200 text-gray-500">
          <th scope="col" className="px-3 py-2 text-left">
            {t('relatedJobs.columns.job')}
          </th>
          {showCompany && (
            <th scope="col" className="px-3 py-2 text-left">
              {t('relatedJobs.columns.company')}
            </th>
          )}
          <th scope="col" className="px-3 py-2 text-left">
            {t('relatedJobs.columns.status')}
          </th>
          <th scope="col" className="px-3 py-2 text-left">
            {t('relatedJobs.columns.invoices')}
          </th>
          <th scope="col" className="px-3 py-2 text-right">
            {t('relatedJobs.columns.invoiced')}
          </th>
        </tr>
      }
      renderRow={(job) => (
        <JobRow
          key={job.job_id}
          job={job}
          statusLabels={statuses.data?.statuses}
          automationId={automationId}
          showCompany={showCompany}
        />
      )}
      footer={
        total !== undefined && (
          <div className="flex justify-end border-t border-gray-200 px-3 py-2 text-sm">
            <span className="mr-3 text-gray-500">{t('relatedJobs.totalInvoiced')}</span>
            <span data-automation-id={`${automationId}-total`} className="font-semibold">
              {formatCurrency(total)}
            </span>
          </div>
        )
      }
    />
  )
}

/** A job status as the job screen names it. Throws on a status the vocabulary
    does not hold: both come from Job.JOB_STATUS_CHOICES, so a miss is a defect. */
function statusLabel(labels: Record<string, string> | undefined, status: string): string {
  const label = labels?.[status]
  if (label === undefined) {
    throw new Error(`Job status '${status}' is not in the status vocabulary`)
  }
  return label
}

function JobRow({
  job,
  statusLabels,
  automationId,
  showCompany,
}: {
  job: CrmJobRow
  /** Undefined only while the vocabulary loads, when the table shows its
      loading state instead of rows. */
  statusLabels: Record<string, string> | undefined
  automationId: string
  showCompany: boolean
}) {
  const { t } = useTranslation('crm')
  return (
    <tr
      data-automation-id={`${automationId}-row-${job.job_id}`}
      className="border-b border-gray-100"
    >
      <td className="px-3 py-2 font-medium text-gray-900">
        <Link to="/jobs/$jobId" params={{ jobId: job.job_id }} className="hover:underline">
          {t('relatedJobs.jobLabel', { number: job.job_number, name: job.name })}
        </Link>
      </td>
      {showCompany && (
        <td className="px-3 py-2">
          {job.company === null ? (
            '—'
          ) : (
            <Link
              to="/crm/companies/$companyId"
              params={{ companyId: job.company.id }}
              className="hover:underline"
            >
              {job.company.name}
            </Link>
          )}
        </td>
      )}
      <td className="px-3 py-2">{statusLabel(statusLabels, job.status)}</td>
      <td className="px-3 py-2">
        {job.invoices.length === 0 ? (
          <span className="text-gray-500">{t('relatedJobs.notInvoiced')}</span>
        ) : (
          <ul className="space-y-0.5">
            {job.invoices.map((invoice) => (
              <li key={invoice.id} data-automation-id={`${automationId}-invoice-${invoice.id}`}>
                {/* A Xero deep link where the sync has one; the number as text
                    where it has not, never an anchor with nowhere to go. */}
                {invoice.online_url === null ? (
                  <span className="font-medium">{invoice.number}</span>
                ) : (
                  <a
                    href={invoice.online_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-blue-700 hover:underline"
                  >
                    {invoice.number}
                  </a>
                )}{' '}
                <span className="text-gray-500">{formatDate(invoice.date)}</span>
              </li>
            ))}
          </ul>
        )}
      </td>
      <td
        data-automation-id={`${automationId}-cell-${job.job_id}-invoiced`}
        className="px-3 py-2 text-right"
      >
        {formatCurrency(job.invoiced_total_excl_tax)}
      </td>
    </tr>
  )
}
