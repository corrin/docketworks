import { createFileRoute, Outlet, redirect } from '@tanstack/react-router'

import { meQueryOptions } from '@/features/auth'
import { AppNavbar, ensureAppShellData } from '@/features/shell'

export const Route = createFileRoute('/_authed')({
  // Authenticated routes check the session and redirect to
  // /login with the attempted path in ?redirect= when unauthenticated.
  // Shell data loads after auth succeeds; its failures are real errors,
  // not a reason to bounce to login.
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.ensureQueryData(meQueryOptions())
    } catch {
      throw redirect({ to: '/login', search: { redirect: location.href } })
    }
    await ensureAppShellData(context.queryClient)
  },
  component: AuthedLayout,
})

function AuthedLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <AppNavbar />
      <Outlet />
    </div>
  )
}
