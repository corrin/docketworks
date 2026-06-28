import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    crm_phone_calls_list: vi.fn(),
    clients_contact_methods_list: vi.fn(),
    clients_search_retrieve: vi.fn(),
    clients_contacts_list: vi.fn(),
    assignPhoneCallNumber: vi.fn(),
  },
}))

vi.mock('@/components/AppLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))

vi.mock('@/components/crm/PhoneCallTable.vue', () => ({
  default: {
    props: ['calls', 'emptyText'],
    template: '<div data-test="phone-call-table">{{ calls.length }} calls</div>',
  },
}))

vi.mock('@/composables/useClientLookup', () => ({
  logClientSearchClick: vi.fn(),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import { api } from '@/api/client'
import CallsPage from '@/pages/crm/calls.vue'

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  vi.mocked(api.crm_phone_calls_list).mockResolvedValue({
    results: [{ id: 'call-1' }],
    count: 12,
    page: 1,
    page_size: 50,
    total_pages: 1,
  } as Awaited<ReturnType<typeof api.crm_phone_calls_list>>)
  vi.mocked(api.clients_contact_methods_list).mockResolvedValue({
    results: [{ id: 'method-1' }],
    count: 7,
    page: 1,
    page_size: 50,
    total_pages: 1,
  } as Awaited<ReturnType<typeof api.clients_contact_methods_list>>)
})

describe('CRM calls pagination', () => {
  it('loads calls and phone methods through page/page_size responses', async () => {
    const wrapper = mount(CallsPage)
    await flushPromises()

    expect(api.crm_phone_calls_list).toHaveBeenCalledWith({
      queries: { page: 1, page_size: 50 },
    })
    expect(api.clients_contact_methods_list).toHaveBeenCalledWith({
      queries: { method_type: 'phone', page: 1, page_size: 50 },
    })
    expect(wrapper.text()).toContain('Showing 1 of 12')
    expect(wrapper.text()).toContain('Showing 1 of 7')
  })
})
