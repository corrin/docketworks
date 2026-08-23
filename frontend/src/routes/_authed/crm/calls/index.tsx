import { createFileRoute } from '@tanstack/react-router'

import { PhoneCallsPage } from '@/features/crm'

export const Route = createFileRoute('/_authed/crm/calls/')({
  component: PhoneCallsPage,
})
