import { waitFor } from '@testing-library/react'
import type { UserEvent } from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { AppNavbar } from './AppNavbar'

function mockUser(overrides: Record<string, unknown>) {
  server.use(
    http.get('*/api/accounts/me/', () =>
      HttpResponse.json({
        id: '11111111-1111-1111-1111-111111111111',
        office_email: 'someone@example.com',
        payroll_email: null,
        first_name: 'Some',
        last_name: 'One',
        preferred_name: null,
        fullName: 'Some One',
        is_office_staff: true,
        is_superuser: false,
        ...overrides,
      }),
    ),
  )
}

/** Menu contents are portalled out of the render container and mounted only
    while open, so every assertion below opens the menu first — the same thing
    a user has to do to reach the link. */
function autoId(id: string): Element | null {
  return document.querySelector(`[data-automation-id="${id}"]`)
}

async function openMenu(user: UserEvent, automationId: string): Promise<void> {
  await waitFor(() => expect(autoId(automationId)).not.toBeNull())
  const trigger = autoId(automationId)
  if (!(trigger instanceof HTMLElement)) throw new Error(`missing menu ${automationId}`)
  await user.click(trigger)
}

describe('AppNavbar — the weekly timesheets link', () => {
  it('offers weekly, leave and the first admin entry to a superuser', async () => {
    mockUser({ is_superuser: true })
    const { user } = renderWithProviders(<AppNavbar />)

    await openMenu(user, 'AppNavbar-timesheets-menu')
    await waitFor(() => {
      expect(autoId('AppNavbar-weekly-timesheets')).not.toBeNull()
      expect(autoId('AppNavbar-leave')).not.toBeNull()
    })

    await user.keyboard('{Escape}')
    await openMenu(user, 'AppNavbar-admin-menu')
    await waitFor(() => expect(autoId('AppNavbar-leave-settings')).not.toBeNull())
  })

  it('closes the menu once an entry is chosen', async () => {
    // The <details> menu this replaced stayed open after a pick, and its
    // summary toggled — so reopening it closed the menu instead.
    mockUser({ is_superuser: true })
    const { user } = renderWithProviders(<AppNavbar />)

    await openMenu(user, 'AppNavbar-timesheets-menu')
    const leave = autoId('AppNavbar-leave')
    if (!(leave instanceof HTMLElement)) throw new Error('missing leave link')
    await user.click(leave)

    await waitFor(() => expect(autoId('AppNavbar-leave')).toBeNull())
  })

  it('closes the menu on Escape', async () => {
    mockUser({ is_superuser: true })
    const { user } = renderWithProviders(<AppNavbar />)

    await openMenu(user, 'AppNavbar-timesheets-menu')
    await waitFor(() => expect(autoId('AppNavbar-leave')).not.toBeNull())

    await user.keyboard('{Escape}')
    await waitFor(() => expect(autoId('AppNavbar-leave')).toBeNull())
  })

  it('is withheld from office staff who are not superusers', async () => {
    // Opus: The page and every payroll endpoint behind it use SuperuserCookieJWTAuth,
    // so offering this link to office staff sent them to a 403 — a link that
    // only ever fails is worse than no link.
    mockUser({ is_office_staff: true, is_superuser: false })
    const { user } = renderWithProviders(<AppNavbar />)

    await waitFor(() => expect(autoId('AppNavbar-logout')).not.toBeNull())
    // Opened, not merely unrendered: the superuser-only entries must be absent
    // from a menu the user has actually pulled down.
    await openMenu(user, 'AppNavbar-timesheets-menu')
    await waitFor(() => expect(autoId('AppNavbar-daily-timesheets')).not.toBeNull())

    expect(autoId('AppNavbar-weekly-timesheets')).toBeNull()
    expect(autoId('AppNavbar-leave')).toBeNull()
    expect(autoId('AppNavbar-admin-menu')).toBeNull()
    expect(autoId('AppNavbar-leave-settings')).toBeNull()
  })
})

describe('AppNavbar — the Reports menu', () => {
  it('offers office staff every report their login can actually read', async () => {
    mockUser({ is_office_staff: true, is_superuser: false })
    const { user } = renderWithProviders(<AppNavbar />)

    await openMenu(user, 'AppNavbar-reports-menu')
    // Opus: a routed report the menu omits is reachable only by typing its
    // URL, which is how all three of these sat unreachable before this menu.
    await waitFor(() => {
      expect(autoId('AppNavbar-sales-forecast')).not.toBeNull()
      expect(autoId('AppNavbar-job-movement')).not.toBeNull()
      expect(autoId('AppNavbar-wip')).not.toBeNull()
    })
    // Payroll is superuser-only behind the API, so office staff must not be
    // offered it — and its section heading must not linger over nothing.
    expect(autoId('AppNavbar-payroll-reconciliation')).toBeNull()
    const menu = autoId('AppNavbar-reports-menu-content')
    expect(menu?.textContent).toContain('Management')
    expect(menu?.textContent).not.toContain('Reconciliation')
  })

  it('adds the payroll report for a superuser', async () => {
    mockUser({ is_office_staff: true, is_superuser: true })
    const { user } = renderWithProviders(<AppNavbar />)

    await openMenu(user, 'AppNavbar-reports-menu')
    await waitFor(() => expect(autoId('AppNavbar-payroll-reconciliation')).not.toBeNull())
    expect(autoId('AppNavbar-reports-menu-content')?.textContent).toContain('Reconciliation')
  })

  it('is withheld from a workshop login', async () => {
    // Every entry is company-wide revenue or payroll, which is why v1 gated
    // the whole menu on is_office_staff rather than gating entries.
    mockUser({ is_office_staff: false })
    const { user } = renderWithProviders(<AppNavbar />)

    await waitFor(() => expect(autoId('AppNavbar-logout')).not.toBeNull())
    expect(autoId('AppNavbar-reports-menu')).toBeNull()

    await openMenu(user, 'AppNavbar-timesheets-menu')
    await waitFor(() => expect(autoId('AppNavbar-daily-timesheets')).not.toBeNull())
    expect(autoId('AppNavbar-sales-forecast')).toBeNull()
  })
})
