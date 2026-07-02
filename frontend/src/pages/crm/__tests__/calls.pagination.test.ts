import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    crm_phone_calls_list: vi.fn(),
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

vi.mock('@/components/crm/PhoneNumberManager.vue', () => ({
  default: {
    template: '<div data-test="phone-number-manager">phone numbers</div>',
  },
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
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
})

describe('CRM calls pagination', () => {
  it('loads recent calls through paginated workflow query', async () => {
    const wrapper = mount(CallsPage)
    await flushPromises()

    expect(api.crm_phone_calls_list).toHaveBeenCalledWith({
      queries: { page: 1, page_size: 50, client_match: 'all', job_link: 'all' },
    })
    expect(wrapper.text()).toContain('Showing 1 of 12')
    expect(wrapper.text()).toContain('Recent Calls')
    expect(wrapper.find('[data-test="phone-number-manager"]').exists()).toBe(true)
  })

  it('loads unmatched calls when the unmatched tab is selected', async () => {
    const wrapper = mount(CallsPage)
    await flushPromises()

    const unmatchedTab = wrapper.findAll('button').find((button) => button.text() === 'Unmatched')
    expect(unmatchedTab).toBeTruthy()
    await unmatchedTab?.trigger('pointerdown')
    await unmatchedTab?.trigger('click')
    await flushPromises()

    expect(api.crm_phone_calls_list).toHaveBeenLastCalledWith({
      queries: { page: 1, page_size: 50, client_match: 'unmatched' },
    })
  })

  it('clears stale calls after refresh failure', async () => {
    const wrapper = mount(CallsPage)
    await flushPromises()

    expect(wrapper.text()).toContain('1 calls')
    vi.mocked(api.crm_phone_calls_list).mockRejectedValue(new Error('Call load failed'))
    const refreshButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Refresh'))
    expect(refreshButton).toBeTruthy()
    await refreshButton?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('0 calls')
    expect(wrapper.text()).toContain('Showing 0 of 0')
  })
})
