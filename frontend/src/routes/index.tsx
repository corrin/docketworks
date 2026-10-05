import { createFileRoute, redirect } from '@tanstack/react-router'

import { defaultLandingPath, resolveSession } from '@/features/auth'

/**
 * '/' is where a sign-in lands when no page was asked for: it sends each
 * person to their own default page. Login, the forced password change and
 * the session check all navigate here rather than each naming a page, so
 * the rule has one home.
 */
export const Route = createFileRoute('/')({
  beforeLoad: async ({ context }) => {
    const session = await resolveSession(context.queryClient)
    if (session.state === 'authenticated') {
      throw redirect({ to: defaultLandingPath(session.user) })
    }
    if (session.state === 'unavailable') throw redirect({ to: '/session-check', search: {} })
    throw redirect({ to: '/login', search: {} })
  },
})
