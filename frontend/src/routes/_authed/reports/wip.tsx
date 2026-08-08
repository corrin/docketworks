import { createFileRoute } from '@tanstack/react-router'

import { WipReportPage } from '@/features/reports'

export const Route = createFileRoute('/_authed/reports/wip')({
  component: WipReportPage,
})
