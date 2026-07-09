import { describe, it, expect, vi, beforeEach } from 'vitest'
import { z } from 'zod'

vi.mock('@/api/client', () => ({
  api: {
    companies_person_links_list: vi.fn(),
    companies_person_links_create: vi.fn(),
    companies_person_links_partial_update: vi.fn(),
    companies_person_links_destroy: vi.fn(),
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}))

import { usePersonManagement } from '../usePersonManagement'
import { schemas } from '@/api/generated/api'

type CompanyPersonLink = z.infer<typeof schemas.CompanyPersonLink>

const buildPerson = (overrides: Partial<CompanyPersonLink> = {}): CompanyPersonLink => ({
  id: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0001',
  company: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0002',
  person: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0003',
  person_name: 'Jane Doe',
  person_email: 'jane@example.com',
  xero_name: 'Jane Doe',
  position: null,
  is_primary: true,
  notes: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00+00:00',
  updated_at: '2026-01-01T00:00:00+00:00',
  phone: '+64 21 555 0100',
  ...overrides,
})

describe('usePersonManagement displayValue (KAN-281)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns empty string when no person is selected', () => {
    const { displayValue } = usePersonManagement()
    expect(displayValue.value).toBe('')
  })

  it('formats the selected person as "name - phone - email"', () => {
    const { displayValue, setSelectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson())
    expect(displayValue.value).toBe('Jane Doe - +64 21 555 0100 - jane@example.com')
  })

  it('skips the phone segment when the person has no phone', () => {
    const { displayValue, setSelectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson({ phone: '' }))
    expect(displayValue.value).toBe('Jane Doe - jane@example.com')
  })

  it('skips the email segment when the person has no email', () => {
    const { displayValue, setSelectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson({ person_email: null }))
    expect(displayValue.value).toBe('Jane Doe - +64 21 555 0100')
  })

  it('shows only the name when the person has neither phone nor email', () => {
    const { displayValue, setSelectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson({ phone: '', person_email: null }))
    expect(displayValue.value).toBe('Jane Doe')
  })

  it('set() splits "name - phone - email" into the selected person', () => {
    const { displayValue, setSelectedPerson, selectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson())

    displayValue.value = 'Bob Smith - 09 555 1234 - bob@example.com'

    expect(selectedPerson.value).toMatchObject({
      person_name: 'Bob Smith',
      phone: '09 555 1234',
      person_email: 'bob@example.com',
    })
  })

  it('set() populates the new-person form when nothing is selected', () => {
    const { displayValue, personForm } = usePersonManagement()

    displayValue.value = 'Bob Smith - 09 555 1234 - bob@example.com'

    expect(personForm.value).toMatchObject({
      name: 'Bob Smith',
      phone: '09 555 1234',
      email: 'bob@example.com',
    })
  })

  it('set() with a blank value clears name, phone and email on the form', () => {
    const { displayValue, personForm } = usePersonManagement()

    displayValue.value = ''

    expect(personForm.value).toMatchObject({
      name: '',
      phone: '',
      email: '',
    })
  })
})
