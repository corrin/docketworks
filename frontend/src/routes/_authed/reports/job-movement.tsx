import { createFileRoute } from '@tanstack/react-router'

import { JobMovementReportPage } from '@/features/reports'

export const Route = createFileRoute('/_authed/reports/job-movement')({
  component: JobMovementReportPage,
})
