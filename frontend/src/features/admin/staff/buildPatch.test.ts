import { describe, expect, it } from 'vitest'

import { buildPatch, snapshot } from './StaffFormDialog'

import type { StaffListItemOut } from '@/api'

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

describe('buildPatch', () => {
  it('always sends password_needs_reset alongside a new password', () => {
    // The server clears the flag on every password set, so a dirty-only diff
    // that omits the unchanged-but-checked box would silently un-flag an
    // account the admin's screen showed flagged.
    const staff = staffRow({ password_needs_reset: true })
    const drafts = snapshot(staff)
    drafts.password = 'Fresh-Pass-9!'
    drafts.password_confirm = 'Fresh-Pass-9!'

    const patch = buildPatch(drafts, staff)

    expect(patch.password).toBe('Fresh-Pass-9!')
    expect(patch.password_needs_reset).toBe(true)
  })

  it('omits an unchanged flag when no password is sent', () => {
    const staff = staffRow({ password_needs_reset: true })
    const drafts = snapshot(staff)
    drafts.preferred_name = 'T'

    const patch = buildPatch(drafts, staff)

    expect(patch).toEqual({ preferred_name: 'T' })
  })

  it('sends an unchecked box as an explicit false with a new password', () => {
    const staff = staffRow({ password_needs_reset: true })
    const drafts = snapshot(staff)
    drafts.password = 'Fresh-Pass-9!'
    drafts.password_confirm = 'Fresh-Pass-9!'
    drafts.flags = { ...drafts.flags, password_needs_reset: false }

    const patch = buildPatch(drafts, staff)

    expect(patch.password_needs_reset).toBe(false)
  })
})
