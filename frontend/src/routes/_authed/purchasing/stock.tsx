import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'

import { StockPage } from '@/features/purchasing'

export const Route = createFileRoute('/_authed/purchasing/stock')({
  validateSearch: z.object({ costLineId: z.uuid().optional(), stockId: z.uuid().optional() }),
  component: StockRoute,
})

function StockRoute() {
  const { costLineId, stockId } = Route.useSearch()
  return <StockPage costLineId={costLineId} stockId={stockId} />
}
