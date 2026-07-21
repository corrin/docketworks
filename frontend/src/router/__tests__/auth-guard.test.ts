import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

vi.mock('@/api/client', () => ({
  api: {
    accounts_me_retrieve: vi.fn(),
    accounts_logout_create: vi.fn(),
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}))

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    createWebHistory: actual.createMemoryHistory,
  }
})

// The guard test never renders — it only asserts navigation outcomes — but
// vue-router v5 warns on any record lacking a component/children, so give each
// mocked record a no-op stub to keep them valid v5 records. Defined inside the
// factory because vi.mock is hoisted above module-scope declarations.
vi.mock('vue-router/auto-routes', () => {
  const Stub = { render: () => null }
  return {
    routes: [
      {
        path: '/kanban',
        name: '/kanban',
        component: Stub,
        meta: { requiresAuth: true, allowWorkshopStaff: true },
      },
      {
        path: '/login',
        name: '/login',
        component: Stub,
        meta: { requiresGuest: true, allowWorkshopStaff: true },
      },
      {
        path: '/session-check',
        name: '/session-check',
        component: Stub,
        meta: { allowWorkshopStaff: true },
      },
    ],
    handleHotUpdate: vi.fn(),
  }
})

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

function setupRouter() {
  setActivePinia(createPinia())
  return { api, authStore: useAuthStore(), router }
}

describe('router auth guard', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await router.replace('/session-check')
    vi.clearAllMocks()
  })

  it('redirects to login when the session check confirms unauthenticated', async () => {
    const { api, router } = setupRouter()
    vi.mocked(api.accounts_me_retrieve).mockRejectedValue({ response: { status: 401 } })

    await router.push('/kanban')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/kanban')
    expect(api.accounts_logout_create).not.toHaveBeenCalled()
  })

  it('uses the session-check route instead of login when cold-start auth is unknown', async () => {
    const { api, router } = setupRouter()
    vi.mocked(api.accounts_me_retrieve).mockRejectedValue(
      Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' }),
    )

    await router.push('/kanban')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('/session-check')
    expect(router.currentRoute.value.query.redirect).toBe('/kanban')
    expect(api.accounts_logout_create).not.toHaveBeenCalled()
  })

  it('keeps an already loaded user on the protected route when auth is unknown', async () => {
    const { api, authStore, router } = setupRouter()
    authStore.user = user
    vi.mocked(api.accounts_me_retrieve).mockRejectedValue(
      Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' }),
    )

    await router.push('/kanban')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('/kanban')
    expect(authStore.user).toEqual(user)
    expect(api.accounts_logout_create).not.toHaveBeenCalled()
  })
})
