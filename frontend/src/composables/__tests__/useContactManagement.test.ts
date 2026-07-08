import { describe, it, expect, vi, beforeEach } from 'vitest'
import { z } from 'zod'

vi.mock('@/api/client', () => ({
  api: {
    clients_contacts_list: vi.fn(),
    clients_contacts_create: vi.fn(),
    clients_contacts_partial_update: vi.fn(),
    clients_contacts_destroy: vi.fn(),
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

import { useContactManagement } from '../useContactManagement'
import { schemas } from '@/api/generated/api'

type ClientContact = z.infer<typeof schemas.ClientContact>

const buildContact = (overrides: Partial<ClientContact> = {}): ClientContact => ({
  id: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0001',
  client: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0002',
  name: 'Jane Doe',
  email: 'jane@example.com',
  position: null,
  is_primary: true,
  notes: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00+00:00',
  updated_at: '2026-01-01T00:00:00+00:00',
  phone: '+64 21 555 0100',
  ...overrides,
})

describe('useContactManagement displayValue (KAN-281)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns empty string when no contact is selected', () => {
    const { displayValue } = useContactManagement()
    expect(displayValue.get()).toBe('')
  })

  it('formats the selected contact as "name - phone - email"', () => {
    const { displayValue, setSelectedContact } = useContactManagement()
    setSelectedContact(buildContact())
    expect(displayValue.get()).toBe('Jane Doe - +64 21 555 0100 - jane@example.com')
  })

  it('skips the phone segment when the contact has no phone', () => {
    const { displayValue, setSelectedContact } = useContactManagement()
    setSelectedContact(buildContact({ phone: '' }))
    expect(displayValue.get()).toBe('Jane Doe - jane@example.com')
  })

  it('skips the email segment when the contact has no email', () => {
    const { displayValue, setSelectedContact } = useContactManagement()
    setSelectedContact(buildContact({ email: null }))
    expect(displayValue.get()).toBe('Jane Doe - +64 21 555 0100')
  })

  it('shows only the name when the contact has neither phone nor email', () => {
    const { displayValue, setSelectedContact } = useContactManagement()
    setSelectedContact(buildContact({ phone: '', email: null }))
    expect(displayValue.get()).toBe('Jane Doe')
  })

  it('set() splits "name - phone - email" into the selected contact', () => {
    const { displayValue, setSelectedContact, selectedContact } = useContactManagement()
    setSelectedContact(buildContact())

    displayValue.set('Bob Smith - 09 555 1234 - bob@example.com')

    expect(selectedContact.value).toMatchObject({
      name: 'Bob Smith',
      phone: '09 555 1234',
      email: 'bob@example.com',
    })
  })

  it('set() populates the new-contact form when nothing is selected', () => {
    const { displayValue, newContactForm } = useContactManagement()

    displayValue.set('Bob Smith - 09 555 1234 - bob@example.com')

    expect(newContactForm.value).toMatchObject({
      name: 'Bob Smith',
      phone: '09 555 1234',
      email: 'bob@example.com',
    })
  })

  it('set() with a blank value clears name, phone and email on the form', () => {
    const { displayValue, newContactForm } = useContactManagement()

    displayValue.set('')

    expect(newContactForm.value).toMatchObject({
      name: '',
      phone: '',
      email: '',
    })
  })
})
