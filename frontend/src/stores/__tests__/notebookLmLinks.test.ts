import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { getMenuLinks } = vi.hoisted(() => ({ getMenuLinks: vi.fn() }))

vi.mock('@/services/notebookLmLinkService', () => ({
  notebookLmLinkService: { getMenuLinks },
}))

import { useNotebookLmLinksStore } from '../notebookLmLinks'

describe('notebookLmLinks store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getMenuLinks.mockReset()
  })

  it('loads the menu links through the service layer', async () => {
    const links = [{ id: 1, name: 'MSM Manual', url: 'https://notebooklm.google.com/notebook/aaa' }]
    getMenuLinks.mockResolvedValue(links)

    const store = useNotebookLmLinksStore()
    await store.loadLinks()

    expect(getMenuLinks).toHaveBeenCalledTimes(1)
    expect(store.links).toEqual(links)
    expect(store.isLoaded).toBe(true)
    expect(store.isLoading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('surfaces a failure without leaving the store loading', async () => {
    getMenuLinks.mockRejectedValue(new Error('network down'))

    const store = useNotebookLmLinksStore()
    await store.loadLinks()

    expect(store.error).toBe('network down')
    expect(store.isLoaded).toBe(false)
    expect(store.isLoading).toBe(false)
  })
})
