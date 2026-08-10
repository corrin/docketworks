import { createFileRoute } from '@tanstack/react-router'

import { PoDetailPage } from '@/features/purchasing'

export const Route = createFileRoute('/_authed/purchasing/po/$poId')({
  component: PoDetailRoute,
})

function PoDetailRoute() {
  const { poId } = Route.useParams()
  return <PoDetailPage poId={poId} />
}
