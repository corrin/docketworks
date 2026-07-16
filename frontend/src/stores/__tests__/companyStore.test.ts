import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api/client'
import { useCompanyStore } from '@/stores/companyStore'

vi.mock('@/api/client', () => ({
  api: {
    companies_people_list: vi.fn(),
  },
}))

const mockedApi = vi.mocked(api)

describe('company store people', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetchCompanyPeople updates companyPeople as a side effect', async () => {
    const store = useCompanyStore()
    const previousCompanyPeople = store.companyPeople
    const people = [
      {
        person_id: 'person-1',
        person_name: 'Jane Doe',
        person_email: 'jane@example.com',
        position: null,
        is_primary: true,
        notes: null,
        primary_phone: '+64 21 555 0100',
      },
    ]
    mockedApi.companies_people_list.mockResolvedValueOnce(people)

    const result = await store.fetchCompanyPeople('company-1')

    expect(result).toBeUndefined()
    expect(store.companyPeople).not.toBe(previousCompanyPeople)
    expect(store.companyPeople['company-1']).toEqual(people)
  })

  it('getCompanyPeople uses cached state and otherwise fetches as a side effect', async () => {
    const store = useCompanyStore()
    mockedApi.companies_people_list.mockResolvedValueOnce([])

    const result = await store.getCompanyPeople('company-1')

    expect(result).toBeUndefined()
    expect(mockedApi.companies_people_list).toHaveBeenCalledWith({
      params: { company_id: 'company-1' },
    })
    expect(store.companyPeople['company-1']).toEqual([])

    await store.getCompanyPeople('company-1')

    expect(mockedApi.companies_people_list).toHaveBeenCalledTimes(1)
  })
})
