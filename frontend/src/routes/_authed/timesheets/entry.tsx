import { createFileRoute, redirect } from '@tanstack/react-router'

import { isIsoDateString } from '@/lib/dates'
import { localIsoDate } from '@/lib/format'
import { hasEveryDefault } from '@/lib/searchDefaults'

import { TimesheetEntryPage, type TimesheetEntrySearch } from '@/features/timesheet'

export const Route = createFileRoute('/_authed/timesheets/entry')({
  validateSearch: (search: Record<string, unknown>): TimesheetEntrySearch => ({
    date: typeof search.date === 'string' && isIsoDateString(search.date) ? search.date : undefined,
    staffId: typeof search.staffId === 'string' ? search.staffId : undefined,
  }),
  // The date is written into a bare URL rather than assumed; the staff
  // member has no default and stays absent until chosen
  // (docs/design-language.md, "Report filters live in the URL").
  beforeLoad: ({ search }) => {
    const filled = { date: search.date ?? localIsoDate() }
    if (!hasEveryDefault<Pick<TimesheetEntrySearch, 'date'>>(search, filled)) {
      throw redirect({ to: '/timesheets/entry', search: { ...search, ...filled }, replace: true })
    }
    return { filled: { ...search, ...filled } }
  },
  component: TimesheetEntryRoute,
})

function TimesheetEntryRoute() {
  const { filled } = Route.useRouteContext()
  const navigate = Route.useNavigate()
  return (
    <TimesheetEntryPage
      search={filled}
      onSearchChange={(next) => void navigate({ search: next })}
      onOpenDaily={(date) => void navigate({ to: '/timesheets/daily', search: { date } })}
    />
  )
}
