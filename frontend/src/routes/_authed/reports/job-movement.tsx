import { createFileRoute, redirect } from '@tanstack/react-router'

import { JobMovementReportPage, jobMovementSearchFromUrl, thisFortnight } from '@/features/reports'
import { hasEveryDefault } from '@/lib/searchDefaults'

export const Route = createFileRoute('/_authed/reports/job-movement')({
  validateSearch: jobMovementSearchFromUrl,
  // This fortnight is the default period, written into a bare URL rather
  // than assumed, so a shared link names the period it showed
  // (docs/design-language.md). Half a period (one bound present) is treated
  // as none: a start without an end is not a period.
  beforeLoad: ({ search }) => {
    const whole = search.start !== undefined && search.end !== undefined ? search : {}
    const preset = thisFortnight()
    const filled = { start: whole.start ?? preset.startDate, end: whole.end ?? preset.endDate }
    if (!hasEveryDefault(whole, filled)) {
      throw redirect({ to: '/reports/job-movement', search: filled, replace: true })
    }
    return { filled }
  },
  component: JobMovementRoute,
})

function JobMovementRoute() {
  const { filled } = Route.useRouteContext()
  const navigate = Route.useNavigate()
  return (
    <JobMovementReportPage
      range={{ startDate: filled.start, endDate: filled.end }}
      onRangeChange={(range) =>
        void navigate({ search: { start: range.startDate, end: range.endDate } })
      }
    />
  )
}
