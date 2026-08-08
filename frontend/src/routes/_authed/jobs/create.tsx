import { createFileRoute } from '@tanstack/react-router'

import { JobCreatePage } from '@/features/job'

export const Route = createFileRoute('/_authed/jobs/create')({
  component: JobCreatePage,
})
