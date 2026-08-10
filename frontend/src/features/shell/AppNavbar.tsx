import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, useRouter } from '@tanstack/react-router'

import { meQueryOptions, useLogout } from '@/features/auth'

/**
 * The app header. Deliberately minimal: menus, mobile navigation and the
 * NotebookLM dropdown arrive with the pages that need them.
 */
export function AppNavbar() {
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const router = useRouter()
  const logout = useLogout()

  const handleLogout = async () => {
    try {
      await logout.mutateAsync({})
    } catch {
      // Backend logout failure must not leave user-scoped local state behind.
    }
    await router.navigate({ to: '/login' })
  }

  return (
    <header className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
      <div className="flex items-center space-x-6">
        <Link to="/kanban" className="text-sm font-semibold">
          DocketWorks
        </Link>
        {/* Without is_office_staff there is no Create Job link at all, so a
            test user missing the flag stalls every job-cluster spec at this
            gate rather than failing anything visibly. */}
        {user.is_office_staff && (
          <Link
            to="/jobs/create"
            data-automation-id="AppNavbar-create-job"
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white transition-colors hover:bg-blue-700"
          >
            Create Job
          </Link>
        )}
        <Link to="/timesheets/daily" className="text-sm text-gray-700 hover:text-gray-900">
          Timesheets
        </Link>
      </div>
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
  )
}
