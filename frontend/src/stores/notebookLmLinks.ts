import { defineStore } from 'pinia'
import { ref } from 'vue'
import { notebookLmLinkService, type NotebookLmLink } from '@/services/notebookLmLinkService'

export const useNotebookLmLinksStore = defineStore('notebookLmLinks', () => {
  const links = ref<NotebookLmLink[]>([])
  const isLoaded = ref(false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function loadLinks() {
    isLoading.value = true
    error.value = null
    try {
      links.value = await notebookLmLinkService.getMenuLinks()
      isLoaded.value = true
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load NotebookLM links'
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
