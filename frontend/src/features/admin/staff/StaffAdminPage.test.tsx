import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { StaffAdminPage } from './StaffAdminPage'

import type { StaffListItemOut } from '@/api'
import { autoId } from '@/test/auto-id'

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
    xero_user_id: null,
    is_office_staff: false,
    is_workshop_staff: true,
    is_superuser: false,
    is_staff_manager: false,
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
