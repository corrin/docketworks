import { createFileRoute } from '@tanstack/react-router'
import { StocktakeListPage } from '@/features/purchasing'
export const Route = createFileRoute('/_authed/purchasing/stocktakes/')({
  component: StocktakeListPage,
})
