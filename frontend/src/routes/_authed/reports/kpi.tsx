import { createFileRoute, redirect } from '@tanstack/react-router'

import { KpiCalendarPage, kpiSearchFromUrl } from '@/features/reports'
import { localIsoMonth } from '@/lib/format'
import { hasEveryDefault } from '@/lib/searchDefaults'

export const Route = createFileRoute('/_authed/reports/kpi')({
  validateSearch: kpiSearchFromUrl,
  // What the page shows is what the address bar says, defaults included: a
  // bare /reports/kpi is redirected to name this month, the hours ladder and
  // whole dollars rather than quietly assuming them, so a link copied today
  // reopens on today's month next month (docs/design-language.md; v1 held
  // the month in component state and a link said nothing about it).
  beforeLoad: ({ search }) => {
    const filled = {
      month: search.month ?? localIsoMonth(),
      target: search.target ?? 'hours',
      decimals: search.decimals ?? 0,
    }
    if (!hasEveryDefault(search, filled)) {
      throw redirect({ to: '/reports/kpi', search: filled, replace: true })
    }
    return { filled }
  },
  component: KpiCalendarRoute,
})

function KpiCalendarRoute() {
  const { filled } = Route.useRouteContext()
  const navigate = Route.useNavigate()
  return (
    <KpiCalendarPage
      {...filled}
      onSearchChange={(next) => void navigate({ search: (prev) => ({ ...prev, ...next }) })}
    />
  )
}
