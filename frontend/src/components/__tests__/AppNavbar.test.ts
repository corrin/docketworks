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

const { navLinks } = vi.hoisted(() => ({
  navLinks: { value: [] as Array<{ id: number; name: string; url: string }> },
}))

vi.mock('@/stores/notebookLmLinks', () => ({
  useNotebookLmLinksStore: () => ({
    get links() {
      return navLinks.value
    },
    loadLinks: vi.fn(),
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

describe('AppNavbar NotebookLM training links', () => {
  async function openResourcesDropdown() {
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

    const resourcesButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Resources'))
    if (!resourcesButton) throw new Error('Resources dropdown button not found')
    await resourcesButton.trigger('click')

    return wrapper
  }

  function trainingAnchors(wrapper: Awaited<ReturnType<typeof openResourcesDropdown>>) {
    return wrapper
      .findAll('a')
      .filter((anchor) => (anchor.attributes('href') ?? '').includes('notebooklm.google.com'))
  }

  it('renders one anchor per store link with the correct href and name', async () => {
    navLinks.value = [
      { id: 1, name: 'MSM Manual', url: 'https://notebooklm.google.com/notebook/aaa' },
      { id: 2, name: 'Safety Handbook', url: 'https://notebooklm.google.com/notebook/bbb' },
    ]

    const wrapper = await openResourcesDropdown()
    const anchors = trainingAnchors(wrapper)

    expect(anchors).toHaveLength(2)
    expect(anchors[0].attributes('href')).toBe('https://notebooklm.google.com/notebook/aaa')
    expect(anchors[0].text()).toContain('MSM Manual')
    expect(anchors[1].attributes('href')).toBe('https://notebooklm.google.com/notebook/bbb')
    expect(anchors[1].text()).toContain('Safety Handbook')
  })

  it('renders no training link when the store has no links', async () => {
    navLinks.value = []

    const wrapper = await openResourcesDropdown()

    expect(trainingAnchors(wrapper)).toHaveLength(0)
  })
})
