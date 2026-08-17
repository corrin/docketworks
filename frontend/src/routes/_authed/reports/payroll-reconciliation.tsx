import { createFileRoute } from '@tanstack/react-router'

import { PayrollReconciliationPage } from '@/features/reports'
import { isIsoDateString, mondayOf } from '@/lib/dates'
import { localIsoDate } from '@/lib/format'

export const Route = createFileRoute('/_authed/reports/payroll-reconciliation')({
  validateSearch: (search: Record<string, unknown>): { week?: string } => ({
    week:
      typeof search.week === 'string' && isIsoDateString(search.week)
        ? mondayOf(search.week)
        : undefined,
  }),
  component: PayrollReconciliationRoute,
})

function PayrollReconciliationRoute() {
  const search = Route.useSearch()
  // The current week is the useful default: this page is reached straight
  // after posting, and posting is always the current payroll week.
  return <PayrollReconciliationPage weekStart={search.week ?? mondayOf(localIsoDate())} />
}
