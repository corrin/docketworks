import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type NotebookLmLink = z.infer<typeof schemas.NotebookLmLink>

export const useNotebookLmLinksStore = defineStore('notebookLmLinks', () => {
  const links = ref<NotebookLmLink[]>([])
  const isLoaded = ref(false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function loadLinks() {
    isLoading.value = true
    error.value = null
    try {
      // The `menu` action returns the enabled links the current user may see;
      // restriction filtering happens server-side.
      links.value = await api.workflow_notebook_lm_links_menu_list()
      isLoaded.value = true
    } catch (e) {
      error.value = (e as Error)?.message || 'Failed to load NotebookLM links'
    } finally {
      isLoading.value = false
    }
  }

  return {
    links,
    isLoaded,
    isLoading,
    error,
    loadLinks,
  }
})
