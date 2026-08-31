import { createFileRoute, redirect } from '@tanstack/react-router'

import { resolveSession } from '@/features/auth'
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage'

// Fable: top-level, NOT under /_authed — that layout's beforeLoad redirects
// flagged sessions here, so nesting under it would loop the guard against
// itself.
export const Route = createFileRoute('/change-password')({
  beforeLoad: async ({ context }) => {
    const session = await resolveSession(context.queryClient)
    if (session.state === 'unauthenticated') {
      throw redirect({ to: '/login', search: {} })
    }
    if (session.state === 'unavailable') {
      throw redirect({ to: '/session-check', search: {} })
    }
  },
  component: ChangePasswordPage,
})
