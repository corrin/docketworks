import { waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { AppNavbar } from './AppNavbar'

function mockUser(overrides: Record<string, unknown>) {
  server.use(
    http.get('*/api/accounts/me/', () =>
      HttpResponse.json({
        id: 'staff-1',
        email: 'someone@example.com',
        fullName: 'Some One',
        is_office_staff: true,
        is_superuser: false,
        ...overrides,
      }),
    ),
  )
}

describe('AppNavbar — the weekly timesheets link', () => {
  it('is offered to a superuser', async () => {
    mockUser({ is_superuser: true })
    const { container } = renderWithProviders(<AppNavbar />)

    await waitFor(() => {
      expect(
        container.querySelector('[data-automation-id="AppNavbar-weekly-timesheets"]'),
      ).not.toBeNull()
    })
  })

  it('is withheld from office staff who are not superusers', async () => {
    // The page and every payroll endpoint behind it use SuperuserCookieJWTAuth,
    // so offering this link to office staff sent them to a 403 — a link that
    // only ever fails is worse than no link.
    mockUser({ is_office_staff: true, is_superuser: false })
    const { container } = renderWithProviders(<AppNavbar />)

    await waitFor(() => {
      expect(container.querySelector('[data-automation-id="AppNavbar-logout"]')).not.toBeNull()
    })
    expect(container.querySelector('[data-automation-id="AppNavbar-weekly-timesheets"]')).toBeNull()
  })
})
