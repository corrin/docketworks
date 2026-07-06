import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  api: {
    companies_jobs_retrieve: vi.fn(),
    linkPhoneCallJob: vi.fn(),
    unlinkPhoneCallJob: vi.fn(),
  },
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import PhoneCallTable from '@/components/crm/PhoneCallTable.vue'

function callWithRecording() {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    call_datetime: '2026-06-02T03:13:01Z',
    company: null,
    company_name: '',
    contact_name: '',
    external_number: '+64272255846',
    our_number: '+6496365131',
    direction: 'outbound',
    duration_seconds: 120,
    job: null,
    recording: {
      filename: '6496365131_-_64272255846_2026-06-02_-_15_13_01.mp3',
      download_url: '/api/crm/phone-call-recordings/recording-1/download/',
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PhoneCallTable recording playback', () => {
  it('renders relative recording urls directly for same-origin audio playback', () => {
    const protectedUrl = '/api/crm/phone-call-recordings/recording-1/download/'
    const wrapper = mount(PhoneCallTable, {
      props: {
        calls: [callWithRecording()],
        emptyText: 'No calls',
      },
    })

    const audio = wrapper.find('audio')
    expect(audio.exists()).toBe(true)
    expect(audio.attributes('src')).toBe(protectedUrl)
    expect(audio.attributes('preload')).toBe('metadata')
  })

  it('does not promote a separate recording download action', () => {
    const wrapper = mount(PhoneCallTable, {
      props: {
        calls: [callWithRecording()],
        emptyText: 'No calls',
      },
    })

    expect(wrapper.find('button[aria-label="Download recording"]').exists()).toBe(false)
  })
})
