import { createFileRoute, redirect } from '@tanstack/react-router'

import { PayrollReconciliationPage, payrollReconciliationSearchFromUrl } from '@/features/reports'
import { mondayOf } from '@/lib/dates'
import { localIsoDate } from '@/lib/format'
import { hasEveryDefault } from '@/lib/searchDefaults'

export const Route = createFileRoute('/_authed/reports/payroll-reconciliation')({
  // The same Monday-snapping rule as the weekly page: a payroll week IS a
  // Monday, and this page is reached from that one carrying its ?week=.
  validateSearch: payrollReconciliationSearchFromUrl,
  // The current week is the useful default: this page is reached straight
  // after posting, and posting is always the current payroll week. Written
  // into the URL with the wage basis rather than assumed, so a shared link
  // shows the week and column it showed (docs/design-language.md).
  beforeLoad: ({ search }) => {
    const filled = { week: search.week ?? mondayOf(localIsoDate()), basis: search.basis ?? 'base' }
    if (!hasEveryDefault(search, filled)) {
      throw redirect({ to: '/reports/payroll-reconciliation', search: filled, replace: true })
    }
    return { filled }
  },
  component: PayrollReconciliationRoute,
})

function PayrollReconciliationRoute() {
  const { filled } = Route.useRouteContext()
  const navigate = Route.useNavigate()
  return (
    <PayrollReconciliationPage
      weekStart={filled.week}
      wageBasis={filled.basis}
      onWageBasisChange={(basis) => void navigate({ search: (prev) => ({ ...prev, basis }) })}
    />
  )
}
