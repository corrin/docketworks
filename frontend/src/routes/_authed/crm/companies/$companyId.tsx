import { createFileRoute } from '@tanstack/react-router'

import { CompanyDetailPage } from '@/features/crm'

export const Route = createFileRoute('/_authed/crm/companies/$companyId')({
  component: CompanyDetailRoute,
})

function CompanyDetailRoute() {
  const { companyId } = Route.useParams()
  return <CompanyDetailPage companyId={companyId} />
}
