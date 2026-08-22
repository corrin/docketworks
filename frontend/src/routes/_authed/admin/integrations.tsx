import { createFileRoute } from '@tanstack/react-router'

import { IntegrationsPage } from '@/features/admin'

export const Route = createFileRoute('/_authed/admin/integrations')({
  component: IntegrationsPage,
})
