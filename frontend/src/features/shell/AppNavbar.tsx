import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, useRouter } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
          <NavMenuLink to="/timesheets/daily" automationId="AppNavbar-daily-timesheets">
            Daily
          </NavMenuLink>
          {user.is_superuser && (
            <>
              <NavMenuLink to="/timesheets/weekly" automationId="AppNavbar-weekly-timesheets">
                Weekly
              </NavMenuLink>
              <NavMenuLink to="/timesheets/leave" automationId="AppNavbar-leave">
                Leave
              </NavMenuLink>
            </>
          )}
        </NavMenu>
        {/* Fable: office staff only — every people endpoint is office_auth,
            the companies report exposes company-wide spend, and every
            /api/crm/phone-calls* route goes through apps/crm/api.py's
            _require_office_staff. */}
        {user.is_office_staff && (
          <NavMenu label="CRM" automationId="AppNavbar-crm-menu">
            <NavMenuLink to="/crm/companies" automationId="AppNavbar-companies">
              Companies
            </NavMenuLink>
            <NavMenuLink to="/crm/people" automationId="AppNavbar-people">
              People
            </NavMenuLink>
            <NavMenuLink to="/crm/calls" automationId="AppNavbar-calls">
              Calls
            </NavMenuLink>
          </NavMenu>
        )}
        {/* Fable: Purchases, v1's label and v1's office-staff gate (the PO
            endpoints themselves are any-staff; the gate is the menu's, as it
            was). Only the two routes that exist are listed: Upload Supplier
            Pricing and Product Mappings are deferred screens, and a deferred
            capability is hidden, not an inert entry. */}
        {user.is_office_staff && (
          <NavMenu label="Purchases" automationId="AppNavbar-purchases-menu">
            <NavMenuLink to="/purchasing/po" automationId="AppNavbar-purchase-orders">
              Purchase Orders
            </NavMenuLink>
            <NavMenuLink to="/purchasing/stock" automationId="AppNavbar-use-stock">
              Use Stock
            </NavMenuLink>
          </NavMenu>
        )}
        {/* Office staff only, as in v1: every entry is company-wide revenue
            or payroll, which a workshop login has no business reading. */}
        {user.is_office_staff && (
          <NavMenu label="Reports" automationId="AppNavbar-reports-menu">
            <DropdownMenuLabel>Management</DropdownMenuLabel>
            <NavMenuLink to="/reports/job-movement" automationId="AppNavbar-job-movement">
              Job Movement
            </NavMenuLink>
            <NavMenuLink to="/reports/sales-forecast" automationId="AppNavbar-sales-forecast">
              Sales Forecast
            </NavMenuLink>
            <NavMenuLink to="/reports/wip" automationId="AppNavbar-wip">
              WIP Report
            </NavMenuLink>
            {/* Opus: superuser, not office staff like its neighbours — every
                endpoint behind this page uses SuperuserCookieJWTAuth, so an
                office-staff login that follows the link reaches a page whose
                every query 403s. The heading travels with its only entry
                rather than heading an empty section. */}
            {user.is_superuser && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Reconciliation</DropdownMenuLabel>
                <NavMenuLink
                  to="/reports/payroll-reconciliation"
                  automationId="AppNavbar-payroll-reconciliation"
                >
                  Payroll (Xero)
                </NavMenuLink>
              </>
            )}
          </NavMenu>
        )}
        {user.is_superuser && (
          <NavMenu label="Admin" automationId="AppNavbar-admin-menu">
            <NavMenuLink to="/admin/leave-settings" automationId="AppNavbar-leave-settings">
              Leave settings
            </NavMenuLink>
            {/* Superuser only: endpoint uses SuperuserCookieJWTAuth, matching the menu gate. */}
            <NavMenuLink to="/admin/company-defaults" automationId="AppNavbar-company-defaults">
              Company Defaults
            </NavMenuLink>
            <NavMenuLink to="/admin/integrations" automationId="AppNavbar-integrations">
              Integrations
            </NavMenuLink>
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

/**
 * A menu-bar dropdown. Radix rather than the `<details>` element this replaced:
 * `<details>` has no menu behaviour at all, only open/closed. It stayed open
 * after picking an item, stayed open when you clicked elsewhere on the page,
 * let Timesheets and Admin both hang open at once, and ignored Escape — and
 * because its summary TOGGLES, a second click closed the menu the user was
 * trying to reach into. v1 hand-rolled the same behaviours Radix provides
 * (AppNavbar.vue: one `activeDropdown` ref, a document click listener, and
 * `activeDropdown = null` on every item), which ADR 0032 says to take from the
 * library instead. Radix also brings the roving-focus `role="menu"` keyboard
 * contract neither v1 nor `<details>` had.
 */
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
    // Non-modal: a menu bar must not make the rest of the page inert or trap
    // focus — the modal variant is for menus that own the screen while open.
    //
    // KNOWN GAP, not fixed by this: after an unsaved-changes guard REFUSES a
    // navigation started from a menu item, the trigger needs two clicks to
    // reopen. Radix toggles on pointerdown, and the guard's window.confirm
    // runs synchronously inside the click handler, leaving Radix's open state
    // out of step with the unmounted content. Reproduced only through the
    // leave-settings E2E; a unit-level reproduction did not isolate it.
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger
        data-automation-id={automationId}
        className="cursor-pointer text-sm text-gray-700 outline-hidden hover:text-gray-900"
      >
        {label} <span aria-hidden="true">▾</span>
      </DropdownMenuTrigger>
      {/* Opus: the panel carries its own id so a test can assert over one
          menu's contents. Asserting over document.body instead passes today
          and stops testing anything the moment another menu uses the same
          word. */}
      <DropdownMenuContent data-automation-id={`${automationId}-content`}>
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** A menu row. `asChild` keeps the Link as the rendered element, so the item
    stays a real anchor — middle-click and open-in-new-tab keep working — while
    Radix still closes the menu on select. */
function NavMenuLink({
  to,
  automationId,
  children,
}: {
  to: string
  automationId: string
  children: ReactNode
}) {
  return (
    <DropdownMenuItem asChild>
      <Link to={to} data-automation-id={automationId} className="block px-3 py-2 text-sm">
        {children}
      </Link>
    </DropdownMenuItem>
  )
}
