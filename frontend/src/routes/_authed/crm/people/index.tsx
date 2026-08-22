import { createFileRoute } from '@tanstack/react-router'

import { PeopleDirectoryPage } from '@/features/crm'

export const Route = createFileRoute('/_authed/crm/people/')({
  component: PeopleDirectoryPage,
})
