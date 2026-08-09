import { createFileRoute } from '@tanstack/react-router'

import { DailyOverviewPage, type DailyOverviewSearch } from '@/features/timesheet'

export const Route = createFileRoute('/_authed/timesheets/daily')({
  validateSearch: (search: Record<string, unknown>): DailyOverviewSearch => ({
    date: typeof search.date === 'string' ? search.date : undefined,
  }),
  component: DailyOverviewRoute,
})

function DailyOverviewRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <DailyOverviewPage
      search={search}
      onDateChange={(date) => void navigate({ search: { date } })}
      onOpenEntry={(staffId, date) =>
        void navigate({ to: '/timesheets/entry', search: { date, staffId } })
      }
    />
  )
}
