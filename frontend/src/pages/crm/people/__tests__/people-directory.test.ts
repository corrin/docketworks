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
      is_active: true,
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

  it('ignores a stale unfiltered response that resolves after a newer search', async () => {
    const searchResponse = {
      results: [
        {
          id: '33333333-3333-4333-8333-333333333333',
          name: 'Bob Searched',
          email: 'bob@example.com',
          primary_phone: '021 555 0200',
          companies: [
            { company_id: '44444444-4444-4444-8444-444444444444', company_name: 'Search Co' },
          ],
        },
      ],
      count: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    }

    function defer<T>() {
      let resolve!: (value: T) => void
      const promise = new Promise<T>((r) => (resolve = r))
      return { promise, resolve }
    }
    const full = defer<typeof response>()
    const search = defer<typeof response>()
    vi.mocked(api.people_list).mockImplementation((opts) =>
      opts.queries?.q === undefined ? full.promise : search.promise,
    )

    const wrapper = mount(PeopleDirectory)
    await wrapper.find('[data-automation-id="PeopleDirectory-search"]').setValue('Bob')
    await wrapper.find('[data-automation-id="PeopleDirectory-search"]').trigger('keydown.enter')

    search.resolve(searchResponse)
    await flushPromises()
    full.resolve(response)
    await flushPromises()

    expect(wrapper.text()).toContain('Bob Searched')
    expect(wrapper.text()).not.toContain('Jane Doe')
  })

  it('shows an Archived badge for inactive people', async () => {
    const archivedResponse = {
      results: [
        {
          id: '55555555-5555-4555-8555-555555555555',
          name: 'Archie Ved',
          email: 'archie@example.com',
          is_active: false,
          primary_phone: '021 555 0300',
          companies: [],
        },
      ],
      count: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    }
    vi.mocked(api.people_list).mockResolvedValue(archivedResponse)

    const wrapper = mount(PeopleDirectory)
    await flushPromises()

    expect(
      wrapper
        .find(
          '[data-automation-id="PeopleDirectory-archived-badge-55555555-5555-4555-8555-555555555555"]',
        )
        .exists(),
    ).toBe(true)
    expect(wrapper.text()).toContain('Archived')
  })

  it('does not show an Archived badge for active people', async () => {
    const wrapper = mount(PeopleDirectory)
    await flushPromises()

    expect(
      wrapper
        .find(
          '[data-automation-id="PeopleDirectory-archived-badge-11111111-1111-4111-8111-111111111111"]',
        )
        .exists(),
    ).toBe(false)
  })

  it('sends include_archived when the show-archived checkbox is toggled on', async () => {
    const wrapper = mount(PeopleDirectory)
    await flushPromises()

    await wrapper.find('[data-automation-id="PeopleDirectory-show-archived"]').setValue(true)
    await flushPromises()

    expect(api.people_list).toHaveBeenLastCalledWith({
      queries: { page: 1, page_size: 50, q: undefined, include_archived: true },
    })
  })
})
