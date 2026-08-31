import { createFileRoute, redirect } from '@tanstack/react-router'

import { type LoginSearch, resolveSession, safeInternalRedirect } from '@/features/auth'
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage'

// Fable: top-level, NOT under /_authed — that layout's beforeLoad redirects
// flagged sessions here, so nesting under it would loop the guard against
// itself. The redirect param preserves the deep link that started the
// session: login and the layout both pass it through, and success returns
// there rather than flattening every forced arrival onto /kanban.
export const Route = createFileRoute('/change-password')({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    redirect: safeInternalRedirect(search.redirect),
  }),
  beforeLoad: async ({ context }) => {
    const session = await resolveSession(context.queryClient)
    if (session.state === 'unauthenticated') {
      throw redirect({ to: '/login', search: {} })
    }
    if (session.state === 'unavailable') {
      throw redirect({ to: '/session-check', search: {} })
    }
  },
  component: ChangePasswordRoute,
})

function ChangePasswordRoute() {
  const { redirect: destination } = Route.useSearch()
  return <ChangePasswordPage redirect={destination} />
}
