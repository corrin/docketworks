import { createFileRoute } from '@tanstack/react-router'

import { isIsoDateString } from '@/lib/dates'

import { WeeklyOverviewPage, type WeeklyOverviewSearch } from '@/features/timesheet'

export const Route = createFileRoute('/_authed/timesheets/weekly')({
  validateSearch: (search: Record<string, unknown>): WeeklyOverviewSearch => ({
    week: typeof search.week === 'string' && isIsoDateString(search.week) ? search.week : undefined,
  }),
  component: WeeklyOverviewRoute,
})

function WeeklyOverviewRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <WeeklyOverviewPage
      search={search}
      onWeekChange={(week) => void navigate({ search: { week } })}
      onOpenDay={(date) => void navigate({ to: '/timesheets/daily', search: { date } })}
      onOpenEntry={(staffId, date) =>
        void navigate({ to: '/timesheets/entry', search: { date, staffId } })
      }
    />
  )
}
