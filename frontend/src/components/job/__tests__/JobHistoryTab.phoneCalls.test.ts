import { describe, expect, it, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_timeline_retrieve: vi.fn().mockResolvedValue({ timeline: [] }),
    crm_phone_calls_list: vi.fn(),
  },
}))

vi.mock('@/components/crm/PhoneCallTable.vue', () => ({
  default: {
    props: ['calls', 'emptyText'],
    emits: ['call-updated'],
    template: `
      <div data-test="phone-call-table">
        {{ calls.length }} calls
        <button
          v-if="calls.length"
          data-test="detach-call"
          @click="$emit('call-updated', { ...calls[0], job: '33333333-3333-4333-8333-333333333333' })"
        >
          detach
        </button>
      </div>
    `,
  },
}))

vi.mock('@/components/ui/collapsible', () => ({
  Collapsible: { template: '<div><slot /></div>' },
  CollapsibleContent: { template: '<div><slot /></div>' },
}))

vi.mock('@/utils/string-formatting', () => ({
  formatDateTime: (value: string) => value,
  formatEventType: (value: string) => value,
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import JobHistoryTab from '@/components/job/JobHistoryTab.vue'

const officeUser = {
  id: '11111111-1111-4111-8111-111111111111',
  username: 'office@example.com',
  email: 'office@example.com',
  first_name: 'Office',
  last_name: 'User',
  preferred_name: null,
  fullName: 'Office User',
  is_office_staff: true,
  is_superuser: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
})

describe('JobHistoryTab linked phone calls', () => {
  it('does not call the office-only CRM endpoint for workshop users', async () => {
    const authStore = useAuthStore()
    authStore.user = { ...officeUser, is_office_staff: false }

    const wrapper = mount(JobHistoryTab, {
      props: { jobId: '22222222-2222-4222-8222-222222222222' },
    })
    await flushPromises()

    expect(api.job_jobs_timeline_retrieve).toHaveBeenCalledOnce()
    expect(api.crm_phone_calls_list).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('Linked Phone Calls')
  })

  it('loads paginated linked calls for office users', async () => {
    const authStore = useAuthStore()
    authStore.user = officeUser
    vi.mocked(api.crm_phone_calls_list).mockResolvedValue({
      results: [{ id: 'call-1' }],
      count: 3,
      page: 1,
      page_size: 50,
      total_pages: 1,
    })

    const wrapper = mount(JobHistoryTab, {
      props: { jobId: '22222222-2222-4222-8222-222222222222' },
    })
    await flushPromises()

    expect(api.crm_phone_calls_list).toHaveBeenCalledWith({
      queries: {
        job: '22222222-2222-4222-8222-222222222222',
        page: 1,
        page_size: 50,
      },
    })
    expect(wrapper.text()).toContain('Showing 1 of 3')
  })

  it('keeps linked call count aligned when a call is detached', async () => {
    const authStore = useAuthStore()
    authStore.user = officeUser
    vi.mocked(api.crm_phone_calls_list).mockResolvedValue({
      results: [
        {
          id: 'call-1',
          job: '22222222-2222-4222-8222-222222222222',
        },
      ],
      count: 3,
      page: 1,
      page_size: 50,
      total_pages: 1,
    })

    const wrapper = mount(JobHistoryTab, {
      props: { jobId: '22222222-2222-4222-8222-222222222222' },
    })
    await flushPromises()

    await wrapper.find('[data-test="detach-call"]').trigger('click')

    expect(wrapper.text()).toContain('Showing 0 of 2')
  })
})
