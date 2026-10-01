import { createFileRoute } from '@tanstack/react-router'

import { SalesForecastPage, salesForecastSearchFromUrl } from '@/features/reports'

export const Route = createFileRoute('/_authed/reports/sales-forecast')({
  validateSearch: salesForecastSearchFromUrl,
  component: SalesForecastRoute,
})

function SalesForecastRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  // No default to write: a bare URL IS the month list. The drill-down writes
  // its month and the back button clears it (docs/design-language.md).
  return (
    <SalesForecastPage
      selectedMonth={search.month ?? null}
      onSelectMonth={(month) => void navigate({ search: month === null ? {} : { month } })}
    />
  )
}
