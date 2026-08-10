import { createFileRoute } from '@tanstack/react-router'

import { StockPage } from '@/features/purchasing'

export const Route = createFileRoute('/_authed/purchasing/stock')({
  component: StockPage,
})
