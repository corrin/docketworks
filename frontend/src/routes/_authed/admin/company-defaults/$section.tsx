import { createFileRoute } from '@tanstack/react-router'

import { CompanyDefaultsPage } from '@/features/admin'

export const Route = createFileRoute('/_authed/admin/company-defaults/$section')({
  component: CompanyDefaultsRoute,
})

function CompanyDefaultsRoute() {
  const { section } = Route.useParams()

  return <CompanyDefaultsPage section={section} />
}
