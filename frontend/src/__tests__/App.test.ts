import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import App from '@/App.vue'
import { useAuthStore } from '@/stores/auth'
import { startSessionReplay, stopSessionReplay } from '@/services/sessionReplayService'

vi.mock('@/api/client', () => ({
  api: {
    accounts_me_retrieve: vi.fn(),
  },
}))

vi.mock('@/services/sessionReplayService', () => ({
  flushSessionReplay: vi.fn().mockResolvedValue(undefined),
  reportFrontendError: vi.fn().mockResolvedValue(undefined),
  startSessionReplay: vi.fn().mockResolvedValue(undefined),
  stopSessionReplay: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

const user = {
  id: '11111111-1111-4111-8111-111111111111',
  username: 'cindy@example.com',
  email: 'cindy@example.com',
  first_name: 'Cindy',
  last_name: 'Admin',
  preferred_name: null,
  fullName: 'Cindy Admin',
  is_office_staff: true,
  is_superuser: false,
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function mountApp() {
  return mount(App, {
    global: {
      stubs: {
        RouterView: true,
        Toaster: true,
      },
    },
  })
}

describe('App session replay lifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('starts session replay after a fresh login authenticates the SPA', async () => {
    const pending = deferred<typeof user>()
    vi.mocked(api.accounts_me_retrieve).mockReturnValue(pending.promise)
    const authStore = useAuthStore()
    const wrapper = mountApp()

    vi.mocked(stopSessionReplay).mockClear()
    authStore.user = user
    await nextTick()

    expect(startSessionReplay).toHaveBeenCalledOnce()
    expect(stopSessionReplay).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('starts session replay when the app mounts already authenticated', async () => {
    vi.mocked(api.accounts_me_retrieve).mockResolvedValue(user)
    const authStore = useAuthStore()
    authStore.user = user

    const wrapper = mountApp()
    await nextTick()

    expect(startSessionReplay).toHaveBeenCalledOnce()

    wrapper.unmount()
  })

  it('stops session replay when the user becomes unauthenticated', async () => {
    const pending = deferred<typeof user>()
    vi.mocked(api.accounts_me_retrieve).mockReturnValue(pending.promise)
    const authStore = useAuthStore()
    authStore.user = user
    const wrapper = mountApp()

    vi.mocked(startSessionReplay).mockClear()
    vi.mocked(stopSessionReplay).mockClear()
    authStore.user = null
    await nextTick()

    expect(startSessionReplay).not.toHaveBeenCalled()
    expect(stopSessionReplay).toHaveBeenCalledOnce()

    wrapper.unmount()
  })
})
