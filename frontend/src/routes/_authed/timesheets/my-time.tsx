import { createFileRoute } from '@tanstack/react-router'

import { isIsoDateString } from '@/lib/dates'

import { WorkshopMyTimePage, type MyTimeSearch } from '@/features/timesheet'

export const Route = createFileRoute('/_authed/timesheets/my-time')({
  validateSearch: (search: Record<string, unknown>): MyTimeSearch => ({
    date: typeof search.date === 'string' && isIsoDateString(search.date) ? search.date : undefined,
  }),
  component: MyTimeRoute,
})

function MyTimeRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <WorkshopMyTimePage
      search={search}
      onDateChange={(date) => void navigate({ search: { date } })}
    />
  )
}
