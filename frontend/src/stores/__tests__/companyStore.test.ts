import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api/client'
import { useCompanyStore } from '@/stores/companyStore'

vi.mock('@/api/client', () => ({
  api: {
    companies_person_links_list: vi.fn(),
  },
}))

const mockedApi = vi.mocked(api)

describe('company store people links', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetchCompanyPersonLinks updates companyPeople as a side effect', async () => {
    const store = useCompanyStore()
    const previousCompanyPeople = store.companyPeople
    const people = [
      {
        id: 'link-1',
        company: 'company-1',
        person: 'person-1',
        person_name: 'Jane Doe',
        person_email: 'jane@example.com',
        position: null,
        is_primary: true,
        notes: null,
        is_active: true,
        created_at: '2026-01-01T00:00:00+00:00',
        updated_at: '2026-01-01T00:00:00+00:00',
        phone: '+64 21 555 0100',
      },
    ]
    mockedApi.companies_person_links_list.mockResolvedValueOnce(people)

    const result = await store.fetchCompanyPersonLinks('company-1')

    expect(result).toBeUndefined()
    expect(store.companyPeople).not.toBe(previousCompanyPeople)
    expect(store.companyPeople['company-1']).toEqual(people)
  })

  it('getCompanyPersonLinks uses cached state and otherwise fetches as a side effect', async () => {
    const store = useCompanyStore()
    mockedApi.companies_person_links_list.mockResolvedValueOnce([])

    const result = await store.getCompanyPersonLinks('company-1')

    expect(result).toBeUndefined()
    expect(mockedApi.companies_person_links_list).toHaveBeenCalledWith({
      queries: { company_id: 'company-1' },
    })
    expect(store.companyPeople['company-1']).toEqual([])

    await store.getCompanyPersonLinks('company-1')

    expect(mockedApi.companies_person_links_list).toHaveBeenCalledTimes(1)
  })
})
