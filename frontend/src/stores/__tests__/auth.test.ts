import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/client', () => ({
  api: {
    accounts_me_retrieve: vi.fn(),
    accounts_logout_create: vi.fn(),
    accounts_token_create: vi.fn(),
  },
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
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('auth store session checks', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('sets the user and returns authenticated when /me/ succeeds', async () => {
    vi.mocked(api.accounts_me_retrieve).mockResolvedValue(user)

    const store = useAuthStore()

    await expect(store.checkSession()).resolves.toBe('authenticated')
    expect(store.user).toEqual(user)
    expect(store.hasCheckedSession).toBe(true)
  })

  it('clears local user only when /me/ confirms the session is unauthorized', async () => {
    vi.mocked(api.accounts_me_retrieve).mockRejectedValue({ response: { status: 401 } })

    const store = useAuthStore()
    store.user = user

    await expect(store.checkSession()).resolves.toBe('unauthenticated')
    expect(store.user).toBeNull()
    expect(store.hasCheckedSession).toBe(true)
    expect(api.accounts_logout_create).not.toHaveBeenCalled()
  })

  it('preserves the current user when /me/ fails without an auth rejection', async () => {
    const networkError = Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })
    vi.mocked(api.accounts_me_retrieve).mockRejectedValue(networkError)

    const store = useAuthStore()
    store.user = user

    await expect(store.checkSession()).resolves.toBe('unknown')
    expect(store.user).toEqual(user)
    expect(store.sessionCheckError).toBe(networkError)
    expect(store.hasCheckedSession).toBe(true)
    expect(api.accounts_logout_create).not.toHaveBeenCalled()
  })

  it('deduplicates concurrent /me/ checks', async () => {
    const pending = deferred<typeof user>()
    vi.mocked(api.accounts_me_retrieve).mockReturnValue(pending.promise)

    const store = useAuthStore()
    const first = store.checkSession()
    const second = store.checkSession()

    expect(api.accounts_me_retrieve).toHaveBeenCalledOnce()

    pending.resolve(user)

    await expect(first).resolves.toBe('authenticated')
    await expect(second).resolves.toBe('authenticated')
  })

  it('reuses an already checked user without another /me/ request', async () => {
    const store = useAuthStore()
    store.user = user
    store.hasCheckedSession = true

    await expect(store.checkSession()).resolves.toBe('authenticated')

    expect(api.accounts_me_retrieve).not.toHaveBeenCalled()
  })
})
