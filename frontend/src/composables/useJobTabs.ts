import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { JobTabsSchema, type JobTabKey } from '@/constants/job-tabs'

export function useJobTabs(defaultTab: JobTabKey = 'estimate') {
  const route = useRoute()
  const router = useRouter()
  const activeTab = ref<JobTabKey>(defaultTab)

  // Parse tab from query string
  const parseTabFromQuery = (value: unknown): JobTabKey | null => {
    const normalized = Array.isArray(value) ? value[0] : value
    const result = JobTabsSchema.safeParse(normalized)
    return result.success ? result.data : null
  }

  // Initialize from URL if present
  const initialTab = parseTabFromQuery(route.query.tab)
  if (initialTab) {
    activeTab.value = initialTab
  }

  // Watch for URL changes (back/forward navigation)
  watch(
    () => route.query.tab,
    (newTab) => {
      const parsed = parseTabFromQuery(newTab)
      if (parsed && parsed !== activeTab.value) {
        activeTab.value = parsed
      }
    },
  )

  function setTab(tab: JobTabKey) {
    if (tab === activeTab.value) return

    activeTab.value = tab

    // Update URL with new tab, preserving other query params
    router.push({
      query: {
        ...route.query,
        tab,
      },
    })
  }

  function isTab(tab: JobTabKey) {
    return activeTab.value === tab
  }

  return {
    activeTab,
    setTab,
    isTab,
  }
}
