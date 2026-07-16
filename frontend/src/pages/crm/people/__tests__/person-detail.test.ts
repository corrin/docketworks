import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  api: {
    people_retrieve: vi.fn(),
    people_partial_update: vi.fn(),
    people_contact_methods_list: vi.fn(),
    people_contact_methods_create: vi.fn(),
    people_contact_methods_partial_update: vi.fn(),
    people_contact_methods_destroy: vi.fn(),
    people_company_links_list: vi.fn(),
    people_company_links_update: vi.fn(),
    people_company_links_destroy: vi.fn(),
    people_archive_create: vi.fn(),
  },
}))
vi.mock('@/components/AppLayout.vue', () => ({ default: { template: '<div><slot /></div>' } }))
vi.mock('@/components/CompanyLookup.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

import { api } from '@/api/client'
import PersonDetailPage from '@/pages/crm/people/[id].vue'
import { toast } from 'vue-sonner'

const personId = '11111111-1111-4111-8111-111111111111'
const companyId = '22222222-2222-4222-8222-222222222222'
const person = {
  id: personId,
  name: 'Jane Doe',
  email: 'jane@example.com',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  primary_phone: '021 555 0100',
  companies: [{ company_id: companyId, company_name: 'Acme Limited' }],
  company_links: [],
}
const inactiveLink = {
  company_id: companyId,
  company_name: 'Acme Limited',
  position: 'Buyer',
  notes: null,
  is_primary: true,
  is_active: false,
}

describe('person detail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.people_retrieve).mockResolvedValue(person)
    vi.mocked(api.people_contact_methods_list).mockResolvedValue([])
    vi.mocked(api.people_company_links_list).mockResolvedValue([inactiveLink])
    vi.mocked(api.people_company_links_update).mockResolvedValue({
      ...inactiveLink,
      is_active: true,
    })
  })

  it('shows inactive company links and restores them', async () => {
    const wrapper = mount(PersonDetailPage, { props: { id: personId } })
    await flushPromises()

    expect(wrapper.text()).toContain('Inactive')
    await wrapper
      .find(`[data-automation-id="PersonDetail-restore-link-${companyId}"]`)
      .trigger('click')
    await flushPromises()

    expect(api.people_company_links_update).toHaveBeenCalledWith(
      { position: 'Buyer', notes: null, is_primary: true },
      { params: { person_id: personId, company_id: companyId } },
    )
  })

  it('updates identity without touching company-link fields', async () => {
    const wrapper = mount(PersonDetailPage, { props: { id: personId } })
    await flushPromises()
    await wrapper.find('[data-automation-id="PersonDetail-name"]').setValue('Jane Smith')
    await wrapper.find('[data-automation-id="PersonDetail-save-identity"]').trigger('click')
    await flushPromises()

    expect(api.people_partial_update).toHaveBeenCalledWith(
      { name: 'Jane Smith', email: 'jane@example.com' },
      { params: { person_id: personId } },
    )
  })

  it('shows blocked-unlink validation and keeps the active link visible', async () => {
    const activeLink = { ...inactiveLink, is_active: true }
    vi.mocked(api.people_company_links_list).mockResolvedValue([activeLink])
    vi.mocked(api.people_company_links_destroy).mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          error: 'Removing this link would create a cross-company phone conflict.',
        },
      },
    })
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    const wrapper = mount(PersonDetailPage, { props: { id: personId } })
    await flushPromises()

    await wrapper
      .find(`[data-automation-id="PersonDetail-remove-link-${companyId}"]`)
      .trigger('click')
    await flushPromises()

    expect(toast.error).toHaveBeenCalledWith(
      'Company link not removed: Removing this link would create a cross-company phone conflict.',
    )
    expect(wrapper.text()).toContain('Active')
    expect(wrapper.text()).not.toContain('Inactive')
    expect(api.people_company_links_list).toHaveBeenCalledOnce()
  })

  it('archives an active person and shows the archived badge', async () => {
    vi.mocked(api.people_archive_create).mockResolvedValue(undefined)
    const wrapper = mount(PersonDetailPage, { props: { id: personId } })
    await flushPromises()

    expect(wrapper.find('[data-automation-id="PersonDetail-archived-badge"]').exists()).toBe(false)
    vi.mocked(api.people_retrieve).mockResolvedValue({ ...person, is_active: false })

    await wrapper.find('[data-automation-id="PersonDetail-archive"]').trigger('click')
    await flushPromises()

    expect(api.people_archive_create).toHaveBeenCalledWith(undefined, {
      params: { person_id: personId },
    })
    expect(toast.success).toHaveBeenCalledWith('Person archived')
    expect(wrapper.find('[data-automation-id="PersonDetail-archived-badge"]').exists()).toBe(true)
    expect(wrapper.find('[data-automation-id="PersonDetail-archive"]').exists()).toBe(false)
  })

  it('does not show the archive button for an already-archived person', async () => {
    vi.mocked(api.people_retrieve).mockResolvedValue({ ...person, is_active: false })
    const wrapper = mount(PersonDetailPage, { props: { id: personId } })
    await flushPromises()

    expect(wrapper.find('[data-automation-id="PersonDetail-archived-badge"]').exists()).toBe(true)
    expect(wrapper.find('[data-automation-id="PersonDetail-archive"]').exists()).toBe(false)
  })
})
