import { useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, Outlet, redirect, useRouter } from '@tanstack/react-router'

import { meQueryOptions, useLogout } from '@/features/auth'

export const Route = createFileRoute('/_authed')({
  // v1 router guard: routes with requiresAuth check the session and bounce to
  // /login with the attempted path in ?redirect= when unauthenticated.
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.ensureQueryData(meQueryOptions())
    } catch {
      throw redirect({ to: '/login', search: { redirect: location.href } })
    }
  },
  component: AuthedLayout,
})

function AuthedLayout() {
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const router = useRouter()
  const logout = useLogout()

  const handleLogout = async () => {
    try {
      await logout.mutateAsync({})
    } catch {
      // v1 ignored backend logout failures — local state is cleared either way.
    }
    await router.navigate({ to: '/login' })
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
        <span className="text-sm font-semibold">DocketWorks</span>
        <div className="flex items-center space-x-4">
          <span className="text-sm text-gray-700">Welcome, {user.fullName}!</span>
          <button
            type="button"
            data-automation-id="AppNavbar-logout"
            onClick={handleLogout}
            className="rounded-md bg-red-500 px-3 py-1.5 text-sm text-white transition-colors hover:bg-red-600"
          >
            Log out
          </button>
        </div>
      </header>
      <Outlet />
    </div>
  )
}
