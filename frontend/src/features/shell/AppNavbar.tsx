import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, useRouter } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { TOUCH_TARGET_CLASS } from '@/components/ui/touch'
import { meQueryOptions, useLogout } from '@/features/auth'
import { setWording } from '@/lib/i18n'

import { KanbanSearchInput } from './KanbanSearchInput'

/**
 * The app header. Deliberately minimal: menus, mobile navigation and the
 * NotebookLM dropdown arrive with the pages that need them.
 */
export function AppNavbar() {
  const { t, i18n } = useTranslation('shell')
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
    <header className="flex flex-wrap items-center justify-between gap-y-2 border-b border-border bg-card px-4 py-2">
      <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
        <Link to="/kanban" className="text-sm font-semibold">
          {t('navbar.brand')}
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
            {t('navbar.createJob')}
          </Link>
        )}
        {/* Any-staff: process_forms_list and process_forms_retrieve use
            CookieJWTAuth — regular staff sign forms day to day, so this menu
            is not office-gated (writes stay office-only behind the Edit
            button on the page itself). */}
        <NavMenu label={t('navbar.formsMenu')} automationId="AppNavbar-forms-menu">
          <NavMenuLink
            to="/process-documents/forms/$category"
            params={{ category: 'safety' }}
            automationId="AppNavbar-forms-safety"
          >
            {t('navbar.formsSafety')}
          </NavMenuLink>
          <NavMenuLink
            to="/process-documents/forms/$category"
            params={{ category: 'training' }}
            automationId="AppNavbar-forms-training"
          >
            {t('navbar.formsTraining')}
          </NavMenuLink>
          <NavMenuLink
            to="/process-documents/forms/$category"
            params={{ category: 'incident' }}
            automationId="AppNavbar-forms-incident"
          >
            {t('navbar.formsIncident')}
          </NavMenuLink>
          <NavMenuLink
            to="/process-documents/forms/$category"
            params={{ category: 'meeting' }}
            automationId="AppNavbar-forms-meeting"
          >
            {t('navbar.formsMeeting')}
          </NavMenuLink>
          <NavMenuLink
            to="/process-documents/forms/$category"
            params={{ category: 'register' }}
            automationId="AppNavbar-forms-register"
          >
            {t('navbar.formsRegister')}
          </NavMenuLink>
        </NavMenu>
        <NavMenu label={t('navbar.timesheetsMenu')} automationId="AppNavbar-timesheets-menu">
          <NavMenuLink to="/timesheets/my-time" automationId="AppNavbar-my-time">
            {t('navbar.myTime')}
          </NavMenuLink>
          {/* Any office staff member approves time; the screen shows no pay. */}
          {user.is_office_staff && (
            <NavMenuLink to="/timesheets/approve" automationId="AppNavbar-approve-time">
              {t('navbar.approveTime')}
            </NavMenuLink>
          )}
          {/* Superuser only: Daily, Weekly and Leave all read endpoints behind
              SuperuserCookieJWTAuth, so any other login reaches a page whose
              every query answers 403. */}
          {user.is_superuser && (
            <>
              <NavMenuLink to="/timesheets/daily" automationId="AppNavbar-daily-timesheets">
                {t('navbar.dailyTimesheets')}
              </NavMenuLink>
              <NavMenuLink to="/timesheets/weekly" automationId="AppNavbar-weekly-timesheets">
                {t('navbar.weeklyTimesheets')}
              </NavMenuLink>
              <NavMenuLink to="/timesheets/leave" automationId="AppNavbar-leave">
                {t('navbar.leave')}
              </NavMenuLink>
            </>
          )}
        </NavMenu>
        {/* Fable: office staff only — every people endpoint is office_auth,
            the companies report exposes company-wide spend, and every
            /api/crm/phone-calls* route goes through apps/crm/api.py's
            _require_office_staff. */}
        {user.is_office_staff && (
          <NavMenu label={t('navbar.crmMenu')} automationId="AppNavbar-crm-menu">
            <NavMenuLink to="/crm/companies" automationId="AppNavbar-companies">
              {t('navbar.companies')}
            </NavMenuLink>
            <NavMenuLink to="/crm/people" automationId="AppNavbar-people">
              {t('navbar.people')}
            </NavMenuLink>
            <NavMenuLink to="/crm/calls" automationId="AppNavbar-calls">
              {t('navbar.calls')}
            </NavMenuLink>
          </NavMenu>
        )}
        {/* Fable: Purchases, v1's label and v1's office-staff gate (the PO
            endpoints themselves are any-staff; the gate is the menu's, as it
            was). Only the two routes that exist are listed: Upload Supplier
            Pricing and Product Mappings are deferred screens, and a deferred
            capability is hidden, not an inert entry. */}
        {user.is_office_staff && (
          <NavMenu label={t('navbar.purchasesMenu')} automationId="AppNavbar-purchases-menu">
            <NavMenuLink to="/purchasing/po" automationId="AppNavbar-purchase-orders">
              {t('navbar.purchaseOrders')}
            </NavMenuLink>
            <NavMenuLink to="/purchasing/stock" automationId="AppNavbar-use-stock">
              {t('navbar.useStock')}
            </NavMenuLink>
            <NavMenuLink to="/purchasing/stocktakes" automationId="AppNavbar-stocktake">
              {t('navbar.stocktake')}
            </NavMenuLink>
          </NavMenu>
        )}
        {/* Office staff only, as in v1: every entry is company-wide revenue
            or payroll, which a workshop login has no business reading. */}
        {user.is_office_staff && (
          <NavMenu label={t('navbar.reportsMenu')} automationId="AppNavbar-reports-menu">
            <DropdownMenuLabel>{t('navbar.managementHeading')}</DropdownMenuLabel>
            <NavMenuLink to="/reports/job-movement" automationId="AppNavbar-job-movement">
              {t('navbar.jobMovement')}
            </NavMenuLink>
            <NavMenuLink to="/reports/kpi" automationId="AppNavbar-kpi-calendar">
              {t('navbar.kpiCalendar')}
            </NavMenuLink>
            <NavMenuLink to="/reports/sales-forecast" automationId="AppNavbar-sales-forecast">
              {t('navbar.salesForecast')}
            </NavMenuLink>
            <NavMenuLink to="/reports/wip" automationId="AppNavbar-wip">
              {t('navbar.wip')}
            </NavMenuLink>
            {/* Opus: superuser, not office staff like its neighbours — every
                endpoint behind this page uses SuperuserCookieJWTAuth, so an
                office-staff login that follows the link reaches a page whose
                every query 403s. The heading travels with its only entry
                rather than heading an empty section. */}
            {user.is_superuser && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>{t('navbar.reconciliationHeading')}</DropdownMenuLabel>
                <NavMenuLink
                  to="/reports/payroll-reconciliation"
                  automationId="AppNavbar-payroll-reconciliation"
                >
                  {t('navbar.payrollReconciliation')}
                </NavMenuLink>
              </>
            )}
          </NavMenu>
        )}
        {user.is_superuser && (
          <NavMenu label={t('navbar.adminMenu')} automationId="AppNavbar-admin-menu">
            <NavMenuLink to="/admin/leave-settings" automationId="AppNavbar-leave-settings">
              {t('navbar.leaveSettings')}
            </NavMenuLink>
            {/* Superuser only: endpoint uses SuperuserCookieJWTAuth, matching the menu gate. */}
            <NavMenuLink to="/admin/company-defaults" automationId="AppNavbar-company-defaults">
              {t('navbar.companyDefaults')}
            </NavMenuLink>
            <NavMenuLink to="/admin/integrations" automationId="AppNavbar-integrations">
              {t('navbar.integrations')}
            </NavMenuLink>
            {/* Superuser only: every staff endpoint uses SuperuserCookieJWTAuth,
                matching the menu gate. */}
            <NavMenuLink to="/admin/staff" automationId="AppNavbar-staff">
              {t('navbar.staff')}
            </NavMenuLink>
            {/* Owner ruling 2026-08-30 — Xero lives under Admin to
                keep the navbar uncluttered for staff who never use it, NOT
                as access control (its endpoints stay office_auth and the
                page works for any office login that knows the URL). */}
            {/* Superuser only: the read endpoints use SuperuserCookieJWTAuth,
                because a replay is an unredacted recording of a colleague's
                screen. The menu gate matches. */}
            <NavMenuLink to="/admin/replays" automationId="AppNavbar-replays">
              {t('navbar.replays')}
            </NavMenuLink>
            <NavMenuLink to="/admin/xero" automationId="AppNavbar-xero">
              {t('navbar.xero')}
            </NavMenuLink>
          </NavMenu>
        )}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-4">
        <KanbanSearchInput />
        {/* Hidden on a phone: there it cost the header a fourth row. */}
        <span className="hidden text-sm text-gray-700 sm:inline">
          {t('navbar.welcome', { name: user.fullName })}
        </span>
        <button
          type="button"
          data-automation-id="AppNavbar-wording"
          title={t('navbar.wordingTitle')}
          aria-pressed={i18n.language === 'proposed'}
          onClick={() => setWording(i18n.language === 'proposed' ? 'en' : 'proposed')}
          className="rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm text-amber-900 hover:bg-amber-100"
        >
          {i18n.language === 'proposed' ? t('navbar.wordingProposed') : t('navbar.wordingCurrent')}
        </button>
        <Link
          to="/change-password"
          data-automation-id="AppNavbar-change-password"
          className={`${TOUCH_TARGET_CLASS} text-sm text-gray-700 hover:text-gray-900 hover:underline`}
        >
          {t('navbar.changePassword')}
        </Link>
        <button
          type="button"
          data-automation-id="AppNavbar-logout"
          onClick={handleLogout}
          className="rounded-md bg-red-500 px-3 py-1.5 text-sm text-white transition-colors hover:bg-red-600"
        >
          {t('navbar.logout')}
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
        className={`${TOUCH_TARGET_CLASS} cursor-pointer text-sm text-gray-700 outline-hidden hover:text-gray-900 max-sm:gap-1`}
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
    Radix still closes the menu on select. `params` is optional and composes
    the same way `Link`'s own prop does, for the handful of menu entries (the
    Forms category links) that target a dynamic route segment. */
function NavMenuLink({
  to,
  params,
  automationId,
  children,
}: {
  to: string
  params?: Record<string, string>
  automationId: string
  children: ReactNode
}) {
  return (
    <DropdownMenuItem asChild>
      <Link
        to={to}
        params={params}
        data-automation-id={automationId}
        className="block px-3 py-2 text-sm"
      >
        {children}
      </Link>
    </DropdownMenuItem>
  )
}
