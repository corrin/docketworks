import { createFileRoute } from '@tanstack/react-router'

import { LeavePage } from '@/features/timesheet'

export const Route = createFileRoute('/_authed/timesheets/leave')({
  component: LeavePage,
})
