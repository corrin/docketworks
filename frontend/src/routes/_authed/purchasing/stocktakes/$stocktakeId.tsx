import { createFileRoute } from '@tanstack/react-router'
import { StocktakeDetailPage } from '@/features/purchasing'
export const Route = createFileRoute('/_authed/purchasing/stocktakes/$stocktakeId')({
  component: Page,
})
function Page() {
  const { stocktakeId } = Route.useParams()
  return <StocktakeDetailPage stocktakeId={stocktakeId} />
}
