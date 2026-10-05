import { createFileRoute, redirect } from '@tanstack/react-router'

import { isIsoDateString } from '@/lib/dates'
import { localIsoDate } from '@/lib/format'
import { hasEveryDefault } from '@/lib/searchDefaults'

import { ApproveTimePage, type ApproveTimeSearch } from '@/features/timesheet'

export const Route = createFileRoute('/_authed/timesheets/approve')({
  validateSearch: (search: Record<string, unknown>): ApproveTimeSearch => ({
    date: typeof search.date === 'string' && isIsoDateString(search.date) ? search.date : undefined,
  }),
  // A bare URL is redirected to name today rather than assuming it, so a
  // copied link reopens on the day it showed (docs/design-language.md).
  beforeLoad: ({ search }) => {
    const filled = { date: search.date ?? localIsoDate() }
    if (!hasEveryDefault(search, filled)) {
      throw redirect({ to: '/timesheets/approve', search: filled, replace: true })
    }
    return { filled }
  },
  component: ApproveTimeRoute,
})

function ApproveTimeRoute() {
  const { filled } = Route.useRouteContext()
  const navigate = Route.useNavigate()
  return (
    <ApproveTimePage search={filled} onDateChange={(date) => void navigate({ search: { date } })} />
  )
}
