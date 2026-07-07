import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
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

describe('catch-all 404 route', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('resolves an unknown URL (legacy /crm/clients bookmark) to the catch-all, not a silent no-match', () => {
    const resolved = router.resolve('/crm/clients')

    expect(resolved.name).toBe('/[...path]')
    expect(resolved.matched.length).toBeGreaterThan(0)
    expect(resolved.params.path).toBe('crm/clients')
  })

  it('keeps auth required and allows workshop staff so the 404 renders instead of a wrong toast', () => {
    const resolved = router.resolve('/crm/clients')

    expect(resolved.meta.requiresAuth).toBe(true)
    expect(resolved.meta.allowWorkshopStaff).toBe(true)
    expect(resolved.meta.title).toBe('Page Not Found - DocketWorks')
  })

  it('still resolves the renamed companies pages to their real routes', () => {
    expect(router.resolve('/crm/companies').name).toBe('/crm/companies/(index)')
    expect(router.resolve('/kanban').name).toBe('/kanban')
  })
})
