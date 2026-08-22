import { createFileRoute } from '@tanstack/react-router'

import { PersonDetailPage } from '@/features/crm'

export const Route = createFileRoute('/_authed/crm/people/$personId')({
  component: PersonDetailRoute,
})

function PersonDetailRoute() {
  const { personId } = Route.useParams()
  return <PersonDetailPage personId={personId} />
}
