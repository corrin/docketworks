import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  api: {
    clients_jobs_retrieve: vi.fn(),
    linkPhoneCallJob: vi.fn(),
    unlinkPhoneCallJob: vi.fn(),
  },
}))

vi.mock('@/plugins/axios', () => ({
  default: {
    get: vi.fn(),
  },
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import axios from '@/plugins/axios'
import PhoneCallTable from '@/components/crm/PhoneCallTable.vue'

const createObjectURL = vi.fn(() => 'blob:recording-audio')
const revokeObjectURL = vi.fn()

function callWithRecording() {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    call_datetime: '2026-06-02T03:13:01Z',
    client: null,
    client_name: '',
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
  Object.defineProperty(window.URL, 'createObjectURL', {
    configurable: true,
    value: createObjectURL,
  })
  Object.defineProperty(window.URL, 'revokeObjectURL', {
    configurable: true,
    value: revokeObjectURL,
  })
  vi.mocked(axios.get).mockResolvedValue({
    data: new Blob(['recorded audio'], { type: 'audio/mpeg' }),
  })
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

    expect(axios.get).not.toHaveBeenCalled()
    const audio = wrapper.find('audio')
    expect(audio.exists()).toBe(true)
    expect(audio.attributes('src')).toBe(protectedUrl)
    expect(audio.attributes('preload')).toBe('metadata')
  })

  it('downloads recordings through authenticated axios when requested', async () => {
    vi.useFakeTimers()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const protectedUrl = '/api/crm/phone-call-recordings/recording-1/download/'
    const wrapper = mount(PhoneCallTable, {
      props: {
        calls: [callWithRecording()],
        emptyText: 'No calls',
      },
    })

    await wrapper.get('button[aria-label="Download recording"]').trigger('click')

    expect(axios.get).toHaveBeenCalledWith(protectedUrl, {
      responseType: 'blob',
      withCredentials: true,
    })
    expect(createObjectURL).toHaveBeenCalledOnce()
    const link = document.querySelector('a[download]')
    expect(link).toBeNull()

    await vi.advanceTimersByTimeAsync(30000)

    expect(revokeObjectURL).toHaveBeenCalledWith('blob:recording-audio')
    click.mockRestore()
    vi.useRealTimers()
  })
})
