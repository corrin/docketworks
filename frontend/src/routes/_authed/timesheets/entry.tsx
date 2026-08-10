import { createFileRoute } from '@tanstack/react-router'

import { isIsoDateString } from '@/lib/dates'

import { TimesheetEntryPage, type TimesheetEntrySearch } from '@/features/timesheet'

export const Route = createFileRoute('/_authed/timesheets/entry')({
  validateSearch: (search: Record<string, unknown>): TimesheetEntrySearch => ({
    date: typeof search.date === 'string' && isIsoDateString(search.date) ? search.date : undefined,
    staffId: typeof search.staffId === 'string' ? search.staffId : undefined,
  }),
  component: TimesheetEntryRoute,
})

function TimesheetEntryRoute() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <TimesheetEntryPage
      search={search}
      onSearchChange={(next) => void navigate({ search: next })}
      onOpenDaily={(date) => void navigate({ to: '/timesheets/daily', search: { date } })}
    />
  )
}
