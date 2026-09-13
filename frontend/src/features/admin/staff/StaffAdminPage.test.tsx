import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { StaffAdminPage } from './StaffAdminPage'

import type { StaffListItemOut } from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'

const LIST = '*/api/accounts/staff/'
const DETAIL = '*/api/accounts/staff/:staffId/'

function staffRow(overrides: Partial<StaffListItemOut> = {}): StaffListItemOut {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    first_name: 'Tara',
    last_name: 'Person',
    preferred_name: null,
    display_name: 'Tara Person',
    office_email: 'tara@example.com',
    payroll_email: null,
    employment_start_date: '2026-01-05',
    pay_basis: null,
    wage_rate: 34.56,
    base_wage_rate: 32,
    date_left: null,
    is_currently_active: true,
    xero_user_id: null,
    is_office_staff: false,
    is_workshop_staff: true,
    is_superuser: false,
    is_staff_manager: false,
    password_needs_reset: false,
    hours_mon: 8,
    hours_tue: 8,
    hours_wed: 8,
    hours_thu: 8,
    hours_fri: 8,
    hours_sat: 0,
    hours_sun: 0,
    icon_url: null,
    ...overrides,
  }
}

async function renderPage() {
  const result = renderWithProviders(<StaffAdminPage />)
  await screen.findByText('tara@example.com')
  return result
}

describe('StaffAdminPage', () => {
  beforeEach(() => {
    server.use(http.get(LIST, () => HttpResponse.json([staffRow()])))
  })

  it('lists staff with their costing rate and status', async () => {
    await renderPage()
    const row = autoId('StaffAdminPage-row-11111111-1111-1111-1111-111111111111')
    expect(row).toHaveTextContent('Tara Person')
    expect(row).toHaveTextContent('$34.56')
    expect(row).toHaveTextContent('Active')
  })

  describe('the Current/Past split', () => {
    const DEPARTED = '33333333-3333-3333-3333-333333333333'
    const LEAVING = '44444444-4444-4444-4444-444444444444'

    beforeEach(() => {
      server.use(
        http.get(LIST, () =>
          HttpResponse.json([
            staffRow(),
            staffRow({
              id: DEPARTED,
              first_name: 'Gone',
              office_email: 'gone@example.com',
              date_left: '2025-12-31',
              is_currently_active: false,
            }),
            staffRow({
              id: LEAVING,
              first_name: 'Notice',
              office_email: 'notice@example.com',
              date_left: '2099-01-31',
              is_currently_active: true,
            }),
          ]),
        ),
      )
    })

    it('shows only currently-employed staff until the Past tab is chosen', async () => {
      // A refactor filtering on `date_left === null` — the rule this screen used
      // before is_currently_active existed — would agree on Tara and Gone and
      // only diverge on Notice, who has a leaving date and is still employed.
      // Losing them from Current is the regression: they still come to work.
      await renderPage()

      expect(queryAutoId(`StaffAdminPage-row-${DEPARTED}`)).toBeNull()
      expect(autoId(`StaffAdminPage-row-${LEAVING}`)).toBeVisible()
    })

    it('moves departed staff to the Past tab and leaves current staff behind', async () => {
      const { user } = await renderPage()

      await user.click(autoId('StaffAdminPage-tab-past'))

      expect(autoId(`StaffAdminPage-row-${DEPARTED}`)).toBeVisible()
      expect(queryAutoId(`StaffAdminPage-row-${LEAVING}`)).toBeNull()
      expect(queryAutoId('StaffAdminPage-row-11111111-1111-1111-1111-111111111111')).toBeNull()
    })

    it('distinguishes a pending leaving date from a past one in the Status cell', async () => {
      await renderPage()
      // The date, not just the word: rendering a bare "Leaving" would tell an
      // office manager someone is going without saying when.
      expect(autoId(`StaffAdminPage-row-${LEAVING}`)).toHaveTextContent('Leaving 31 Jan 2099')
    })

    it('narrows the visible rows to those matching the quick filter', async () => {
      const { user } = await renderPage()

      await user.type(autoId('StaffAdminPage-search'), 'notice')

      expect(autoId(`StaffAdminPage-row-${LEAVING}`)).toBeVisible()
      expect(queryAutoId('StaffAdminPage-row-11111111-1111-1111-1111-111111111111')).toBeNull()
    })
  })

  it('creates a staff member and the new row appears without a refetch', async () => {
    const bodies: unknown[] = []
    const created = staffRow({
      id: '22222222-2222-2222-2222-222222222222',
      first_name: 'New',
      office_email: 'new@example.com',
    })
    server.use(
      http.post(LIST, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const { user } = await renderPage()

    await user.click(autoId('StaffAdminPage-new-staff'))
    await screen.findByText('New Staff')
    await user.type(autoId('StaffFormDialog-first-name'), 'New')
    await user.type(autoId('StaffFormDialog-last-name'), 'Member')
    await user.type(autoId('StaffFormDialog-email'), 'new@example.com')
    await user.type(autoId('StaffFormDialog-password'), 'a-Password-1!')
    await user.type(autoId('StaffFormDialog-password-confirm'), 'a-Password-1!')
    await user.click(autoId('StaffFormDialog-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      office_email: 'new@example.com',
      password: 'a-Password-1!',
    })
    // Derived on the server; must never ride a request.
    expect(bodies[0]).not.toHaveProperty('wage_rate')
    await screen.findByText('new@example.com')
  })

  it('a payroll-only staff member submits without an office email', async () => {
    const bodies: unknown[] = []
    const created = staffRow({
      id: '33333333-3333-3333-3333-333333333333',
      first_name: 'Wage',
      office_email: null,
      payroll_email: 'wage@example.com',
    })
    server.use(
      http.post(LIST, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const { user } = await renderPage()

    await user.click(autoId('StaffAdminPage-new-staff'))
    await screen.findByText('New Staff')
    await user.type(autoId('StaffFormDialog-first-name'), 'Wage')
    await user.type(autoId('StaffFormDialog-last-name'), 'Worker')
    await user.type(autoId('StaffFormDialog-payroll-email'), 'wage@example.com')
    await user.type(autoId('StaffFormDialog-password'), 'a-Password-1!')
    await user.type(autoId('StaffFormDialog-password-confirm'), 'a-Password-1!')
    await user.click(autoId('StaffFormDialog-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ payroll_email: 'wage@example.com' })
    expect(bodies[0]).not.toHaveProperty('office_email')
    // The list identifies the new row by the one address it has.
    await screen.findByText('wage@example.com')
  })

  it('with both emails blank the dialog refuses locally', async () => {
    const { user } = await renderPage()

    await user.click(autoId('StaffAdminPage-new-staff'))
    await screen.findByText('New Staff')
    await user.type(autoId('StaffFormDialog-first-name'), 'No')
    await user.type(autoId('StaffFormDialog-last-name'), 'Email')
    await user.type(autoId('StaffFormDialog-password'), 'a-Password-1!')
    await user.type(autoId('StaffFormDialog-password-confirm'), 'a-Password-1!')
    await user.click(autoId('StaffFormDialog-submit'))

    expect(autoId('StaffFormDialog-validation')).toHaveTextContent(
      'At least one email is required.',
    )
  })

  it('a typed negative wage is refused locally, not sent', async () => {
    const { user } = await renderPage()

    await user.click(autoId('StaffAdminPage-edit-staff-11111111-1111-1111-1111-111111111111'))
    await screen.findByText('Edit Staff')
    await user.clear(autoId('StaffFormDialog-base-wage-rate'))
    await user.type(autoId('StaffFormDialog-base-wage-rate'), '-5')
    await user.click(autoId('StaffFormDialog-submit'))

    expect(autoId('StaffFormDialog-validation')).toHaveTextContent(
      'The base wage rate cannot be negative.',
    )
  })

  it('editing sends only the dirty fields', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch(DETAIL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(staffRow({ preferred_name: 'T' }))
      }),
    )
    const { user } = await renderPage()

    await user.click(autoId('StaffAdminPage-edit-staff-11111111-1111-1111-1111-111111111111'))
    await screen.findByText('Edit Staff')
    await user.type(autoId('StaffFormDialog-preferred-name'), 'T')
    await user.click(autoId('StaffFormDialog-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ preferred_name: 'T' })
  })
})
