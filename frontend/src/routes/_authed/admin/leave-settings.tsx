import { createFileRoute } from '@tanstack/react-router'

import { LeaveSettingsPage } from '@/features/admin'

export const Route = createFileRoute('/_authed/admin/leave-settings')({
  component: LeaveSettingsPage,
})
