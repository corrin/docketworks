import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia } from 'pinia'

vi.mock('@/composables/useAppLayout', () => ({
  useAppLayout: () => ({
    userInfo: ref({
      is_office_staff: true,
      is_superuser: false,
    }),
    handleLogout: vi.fn(),
  }),
}))

vi.mock('@/stores/processDocuments', () => ({
  useProcessDocumentsStore: () => ({
    categories: {
      forms: [],
      procedures: [],
    },
    loadCategories: vi.fn(),
  }),
}))

import AppNavbar from '../AppNavbar.vue'

function buildRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/kanban', component: { template: '<div />' } },
      { path: '/jobs/create', component: { template: '<div />' } },
      { path: '/schedule', component: { template: '<div />' } },
    ],
  })
}

describe('AppNavbar search URL sync', () => {
  it('clears the search input when the URL query is removed', async () => {
    const router = buildRouter()
    await router.push('/kanban')
    await router.isReady()

    const wrapper = mount(AppNavbar, {
      global: {
        plugins: [router, createPinia()],
        stubs: {
          WorkshopOfficeToggle: true,
        },
      },
    })
    const input = wrapper.find('input[placeholder="Search jobs..."]')

    await router.replace({ path: '/kanban', query: { q: 'temp' } })
    await router.isReady()
    expect((input.element as HTMLInputElement).value).toBe('temp')

    await input.setValue('stale search')

    await router.replace({ path: '/kanban', query: {} })
    await router.isReady()

    expect((input.element as HTMLInputElement).value).toBe('')
  })
})
