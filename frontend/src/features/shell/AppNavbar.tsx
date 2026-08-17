import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, useRouter } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { meQueryOptions, useLogout } from '@/features/auth'

import { KanbanSearchInput } from './KanbanSearchInput'

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
        <NavMenu label="Timesheets" automationId="AppNavbar-timesheets-menu">
          <Link to="/timesheets/daily" className="block px-3 py-2 text-sm hover:bg-slate-50">
            Daily
          </Link>
          {user.is_superuser && (
            <>
              <Link
                to="/timesheets/weekly"
                data-automation-id="AppNavbar-weekly-timesheets"
                className="block px-3 py-2 text-sm hover:bg-slate-50"
              >
                Weekly
              </Link>
              <Link
                to="/timesheets/leave"
                data-automation-id="AppNavbar-leave"
                className="block px-3 py-2 text-sm hover:bg-slate-50"
              >
                Leave
              </Link>
            </>
          )}
        </NavMenu>
        {user.is_superuser && (
          <NavMenu label="Admin" automationId="AppNavbar-admin-menu">
            <Link
              to="/admin/leave-settings"
              data-automation-id="AppNavbar-leave-settings"
              className="block px-3 py-2 text-sm hover:bg-slate-50"
            >
              Leave settings
            </Link>
          </NavMenu>
        )}
      </div>
      <div className="flex items-center space-x-4">
        <KanbanSearchInput />
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

function NavMenu({
  label,
  automationId,
  children,
}: {
  label: string
  automationId: string
  children: ReactNode
}) {
  return (
    <details className="group relative">
      <summary
        data-automation-id={automationId}
        className="cursor-pointer list-none text-sm text-gray-700 hover:text-gray-900"
      >
        {label} <span aria-hidden="true">▾</span>
      </summary>
      <div className="absolute left-0 top-full z-40 mt-2 min-w-44 overflow-hidden rounded-md border border-slate-200 bg-white py-1 shadow-lg">
        {children}
      </div>
    </details>
  )
}
