import { createFileRoute } from '@tanstack/react-router'

import { CompaniesListPage } from '@/features/crm'

export const Route = createFileRoute('/_authed/crm/companies/')({
  component: CompaniesListPage,
})
