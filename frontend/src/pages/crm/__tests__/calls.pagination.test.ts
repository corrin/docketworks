import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    crm_phone_calls_list: vi.fn(),
  },
}))

const { dataFreshnessSubscribe } = vi.hoisted(() => ({
  dataFreshnessSubscribe: vi.fn(() => vi.fn()),
}))

vi.mock('@/composables/useDataFreshness', () => ({
  dataFreshness: {
    subscribe: dataFreshnessSubscribe,
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
import { dataFreshness } from '@/composables/useDataFreshness'
import CallsPage from '@/pages/crm/calls.vue'

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  dataFreshnessSubscribe.mockReturnValue(vi.fn())
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
    // reka-ui's TabsTrigger activates on left-button mousedown, not click.
    await unmatchedTab?.trigger('mousedown', { button: 0 })
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

  it('does not self-refresh on a timer', async () => {
    vi.useFakeTimers()
    const setIntervalSpy = vi.spyOn(window, 'setInterval')
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    mount(CallsPage)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(60_000)

    expect(setIntervalSpy).not.toHaveBeenCalled()
    expect(clearIntervalSpy).not.toHaveBeenCalled()
    expect(api.crm_phone_calls_list).toHaveBeenCalledTimes(1)

    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
    vi.useRealTimers()
  })

  it('reloads when crm_calls data freshness marks the dataset stale', async () => {
    let staleCallback: (() => void | Promise<void>) | null = null
    const unsubscribe = vi.fn()
    vi.mocked(dataFreshness.subscribe).mockImplementation((key, callback) => {
      if (key === 'crm_calls') staleCallback = callback
      return unsubscribe
    })

    const wrapper = mount(CallsPage)
    await flushPromises()

    expect(dataFreshness.subscribe).toHaveBeenCalledWith('crm_calls', expect.any(Function))
    expect(api.crm_phone_calls_list).toHaveBeenCalledTimes(1)

    staleCallback?.()
    await flushPromises()

    expect(api.crm_phone_calls_list).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    expect(unsubscribe).toHaveBeenCalledOnce()
  })
})
