import { describe, it, expect, vi, beforeEach } from 'vitest'
import { z } from 'zod'

vi.mock('@/api/client', () => ({
  api: {
    companies_people_list: vi.fn(),
    companies_people_create: vi.fn(),
    companies_people_phone_ownership_create: vi.fn(),
    people_company_links_update: vi.fn(),
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
import { api } from '@/api/client'

type CompanyPerson = z.infer<typeof schemas.CompanyPerson>
type PhonePersonMatch = z.infer<typeof schemas.PhonePersonMatch>

const buildPerson = (overrides: Partial<CompanyPerson> = {}): CompanyPerson => ({
  person_id: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0003',
  person_name: 'Jane Doe',
  person_email: 'jane@example.com',
  position: null,
  is_primary: true,
  notes: null,
  primary_phone: '+64 21 555 0100',
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
    setSelectedPerson(buildPerson({ primary_phone: '' }))
    expect(displayValue.value).toBe('Jane Doe - jane@example.com')
  })

  it('skips the email segment when the person has no email', () => {
    const { displayValue, setSelectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson({ person_email: null }))
    expect(displayValue.value).toBe('Jane Doe - +64 21 555 0100')
  })

  it('shows only the name when the person has neither phone nor email', () => {
    const { displayValue, setSelectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson({ primary_phone: '', person_email: null }))
    expect(displayValue.value).toBe('Jane Doe')
  })

  it('set() splits "name - phone - email" into the selected person', () => {
    const { displayValue, setSelectedPerson, selectedPerson } = usePersonManagement()
    setSelectedPerson(buildPerson())

    displayValue.value = 'Bob Smith - 09 555 1234 - bob@example.com'

    expect(selectedPerson.value).toMatchObject({
      person_name: 'Bob Smith',
      primary_phone: '09 555 1234',
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

describe('usePersonManagement duplicate phone prevention', () => {
  const companyId = 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0002'
  const otherCompanyId = 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0004'
  const match: PhonePersonMatch = {
    person_id: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0003',
    person_name: 'Jane Doe',
    person_email: 'jane@example.com',
    company_links: [
      {
        company_id: otherCompanyId,
        company_name: 'Other Company',
        position: null,
        notes: null,
        is_primary: true,
        is_active: true,
      },
    ],
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.companies_people_list).mockResolvedValue([])
  })

  it('offers existing people instead of creating a duplicate', async () => {
    const secondMatch = {
      ...match,
      person_id: 'f6b4a1e2-0f7c-4b7d-9c65-3f2f9a1c0005',
      person_name: 'Jane Smith',
    }
    vi.mocked(api.companies_people_phone_ownership_create).mockResolvedValue({
      status: 'people',
      normalized_phone: '+64215550100',
      can_create_person: false,
      people: [match, secondMatch],
      companies: [],
    })
    const manager = usePersonManagement()
    await manager.openModal(companyId, 'Current Company')
    manager.personForm.value = {
      ...manager.personForm.value,
      name: 'Jane Duplicate',
      phone: '021 555 0100',
    }

    expect(await manager.createNewPerson()).toBe(false)
    expect(manager.phoneOwnership.value?.people).toEqual([match, secondMatch])
    expect(api.companies_people_create).not.toHaveBeenCalled()
  })

  it('allows an explicit separate identity only when the ownership result permits it', async () => {
    vi.mocked(api.companies_people_phone_ownership_create).mockResolvedValue({
      status: 'people',
      normalized_phone: '+64215550100',
      can_create_person: true,
      people: [
        {
          ...match,
          company_links: [
            {
              company_id: companyId,
              company_name: 'Current Company',
              position: null,
              notes: null,
              is_primary: true,
              is_active: true,
            },
          ],
        },
      ],
      companies: [],
    })
    vi.mocked(api.companies_people_create).mockResolvedValue(buildPerson())
    vi.mocked(api.companies_people_list)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([buildPerson()])
    const manager = usePersonManagement()
    await manager.openModal(companyId, 'Current Company')
    manager.personForm.value = {
      ...manager.personForm.value,
      name: 'Household Contact',
      phone: '021 555 0100',
    }

    expect(await manager.createNewPerson()).toBe(false)
    expect(await manager.createNewPerson(true)).toBe(true)
    expect(api.companies_people_create).toHaveBeenCalledOnce()
  })

  it('blocks company-owned and internal numbers without attempting creation', async () => {
    vi.mocked(api.companies_people_phone_ownership_create).mockResolvedValue({
      status: 'company',
      normalized_phone: '+6495550100',
      can_create_person: false,
      people: [],
      companies: [{ company_id: otherCompanyId, company_name: 'Other Company' }],
    })
    const manager = usePersonManagement()
    await manager.openModal(companyId, 'Current Company')
    manager.personForm.value = {
      ...manager.personForm.value,
      name: 'Invalid Owner',
      phone: '09 555 0100',
    }

    expect(await manager.createNewPerson()).toBe(false)
    expect(manager.phoneOwnership.value?.status).toBe('company')
    expect(api.companies_people_create).not.toHaveBeenCalled()
  })

  it('surfaces a typed 409 race as the same candidate workflow', async () => {
    const conflict = {
      status: 'people' as const,
      normalized_phone: '+64215550100',
      can_create_person: false,
      people: [match],
      companies: [],
    }
    vi.mocked(api.companies_people_phone_ownership_create).mockResolvedValue({
      ...conflict,
      status: 'available',
      people: [],
    })
    vi.mocked(api.companies_people_create).mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: conflict },
    })
    const manager = usePersonManagement()
    await manager.openModal(companyId, 'Current Company')
    manager.personForm.value = {
      ...manager.personForm.value,
      name: 'Racing Person',
      phone: '021 555 0100',
    }

    expect(await manager.createNewPerson()).toBe(false)
    expect(manager.phoneOwnership.value).toEqual(conflict)
  })

  it('links a cross-company match without changing its identity', async () => {
    vi.mocked(api.people_company_links_update).mockResolvedValue({
      company_id: companyId,
      company_name: 'Current Company',
      position: null,
      notes: null,
      is_primary: true,
      is_active: true,
    })
    vi.mocked(api.companies_people_list)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([buildPerson()])
    const manager = usePersonManagement()
    await manager.openModal(companyId, 'Current Company')

    expect(await manager.linkExistingPerson(match)).toBe(true)
    expect(api.people_company_links_update).toHaveBeenCalledWith(
      expect.objectContaining({ is_primary: true }),
      { params: { person_id: match.person_id, company_id: companyId } },
    )
    expect(manager.selectedPerson.value?.person_id).toBe(match.person_id)
  })

  it('selects an already-linked person without rewriting the link', async () => {
    const linkedMatch: PhonePersonMatch = {
      ...match,
      company_links: [
        {
          company_id: companyId,
          company_name: 'Current Company',
          position: 'Buyer',
          notes: 'Keep this relationship data',
          is_primary: true,
          is_active: true,
        },
      ],
    }
    vi.mocked(api.companies_people_list)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([buildPerson()])
    const manager = usePersonManagement()
    await manager.openModal(companyId, 'Current Company')

    expect(await manager.linkExistingPerson(linkedMatch)).toBe(true)
    expect(api.people_company_links_update).not.toHaveBeenCalled()
    expect(manager.selectedPerson.value?.person_id).toBe(linkedMatch.person_id)
  })
})
