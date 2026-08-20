import { createFileRoute } from '@tanstack/react-router'

import { SalesForecastPage } from '@/features/reports'

export const Route = createFileRoute('/_authed/reports/sales-forecast')({
  component: SalesForecastPage,
})
