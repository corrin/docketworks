import { createFileRoute } from '@tanstack/react-router'

import { PayrollReconciliationPage } from '@/features/reports'
import { weeklySearchFromUrl } from '@/features/timesheet'
import { mondayOf } from '@/lib/dates'
import { localIsoDate } from '@/lib/format'

export const Route = createFileRoute('/_authed/reports/payroll-reconciliation')({
  // The same Monday-snapping rule as the weekly page: a payroll week IS a
  // Monday, and this page is reached from that one carrying its ?week=.
  validateSearch: weeklySearchFromUrl,
  component: PayrollReconciliationRoute,
})

function PayrollReconciliationRoute() {
  const search = Route.useSearch()
  // The current week is the useful default: this page is reached straight
  // after posting, and posting is always the current payroll week.
  return <PayrollReconciliationPage weekStart={search.week ?? mondayOf(localIsoDate())} />
}
