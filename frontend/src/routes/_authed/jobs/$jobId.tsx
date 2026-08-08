import { createFileRoute } from '@tanstack/react-router'

import { getFullJobOptions } from '@/api'
import { isJobTabKey, JobDetailPage, type JobTabKey } from '@/features/job'

export interface JobDetailSearch {
  new?: string
  tab?: JobTabKey
}

export const Route = createFileRoute('/_authed/jobs/$jobId')({
  validateSearch: (search: Record<string, unknown>): JobDetailSearch => ({
    new: typeof search.new === 'string' ? search.new : undefined,
    tab: typeof search.tab === 'string' && isJobTabKey(search.tab) ? search.tab : undefined,
  }),
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(getFullJobOptions({ path: { job_id: params.jobId } })),
  component: JobDetailRoute,
})

function JobDetailRoute() {
  const { jobId } = Route.useParams()
  const { tab } = Route.useSearch()
  const navigate = Route.useNavigate()

  return (
    <JobDetailPage
      jobId={jobId}
      activeTab={tab ?? 'estimate'}
      onChangeTab={(nextTab) => navigate({ search: (previous) => ({ ...previous, tab: nextTab }) })}
    />
  )
}
