import { createFileRoute } from '@tanstack/react-router'

import { StaffAdminPage } from '@/features/admin'

export const Route = createFileRoute('/_authed/admin/staff')({
  component: StaffAdminPage,
})
