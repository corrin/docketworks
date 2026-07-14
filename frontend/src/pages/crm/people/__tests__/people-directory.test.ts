import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({ api: { people_list: vi.fn() } }))
vi.mock('@/components/AppLayout.vue', () => ({ default: { template: '<div><slot /></div>' } }))
vi.mock('@/components/CompanyLookup.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/PersonSelector.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-sonner', () => ({ toast: { error: vi.fn() } }))

import { api } from '@/api/client'
import PeopleDirectory from '@/pages/crm/people/(index).vue'

const response = {
  results: [
    {
      id: '11111111-1111-4111-8111-111111111111',
      name: 'Jane Doe',
      email: 'jane@example.com',
      primary_phone: '021 555 0100',
      companies: [
        {
          company_id: '22222222-2222-4222-8222-222222222222',
          company_name: 'Acme Limited',
        },
      ],
    },
  ],
  count: 1,
  page: 1,
  page_size: 50,
  total_pages: 1,
}

describe('people directory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.people_list).mockResolvedValue(response)
  })

  it('renders person identities with their companies', async () => {
    const wrapper = mount(PeopleDirectory)
    await flushPromises()

    expect(wrapper.text()).toContain('Jane Doe')
    expect(wrapper.text()).toContain('Acme Limited')
    expect(api.people_list).toHaveBeenCalledWith({
      queries: { page: 1, page_size: 50, q: undefined },
    })
  })

  it('sends search to the paginated people endpoint', async () => {
    const wrapper = mount(PeopleDirectory)
    await flushPromises()
    await wrapper.find('[data-automation-id="PeopleDirectory-search"]').setValue('Jane')
    await wrapper.find('[data-automation-id="PeopleDirectory-search"]').trigger('keydown.enter')
    await flushPromises()

    expect(api.people_list).toHaveBeenLastCalledWith({
      queries: { page: 1, page_size: 50, q: 'Jane' },
    })
  })
})
