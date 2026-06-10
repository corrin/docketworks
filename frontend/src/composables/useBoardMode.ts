import { ref, computed, onMounted } from 'vue'
import { useDeviceDetection } from '@/composables/useDeviceDetection'
import { safeSessionStorage } from '@/utils/safe-storage'

export type BoardMode = 'workshop' | 'office'

const STORAGE_KEY = 'boardMode'

// Singleton pattern - shared state across all consumers
const mode = ref<BoardMode | null>(null)
const hasUserExplicitlyChosen = ref(false)
const isInitialized = ref(false)

export function useBoardMode() {
  const { isDesktop } = useDeviceDetection()

  // Compute default based on device
  const defaultMode = computed<BoardMode>(() => {
    return isDesktop.value ? 'office' : 'workshop'
  })

  // The active mode - user choice takes precedence over device default
  const activeMode = computed<BoardMode>(() => {
    if (hasUserExplicitlyChosen.value && mode.value) {
      return mode.value
    }
    return defaultMode.value
  })

  const isWorkshopMode = computed(() => activeMode.value === 'workshop')
  const isOfficeMode = computed(() => activeMode.value === 'office')

  // Set mode explicitly (user action)
  const setMode = (newMode: BoardMode) => {
    mode.value = newMode
    hasUserExplicitlyChosen.value = true
    safeSessionStorage.set(STORAGE_KEY, newMode)
  }

  // Toggle between modes
  const toggleMode = () => {
    setMode(activeMode.value === 'workshop' ? 'office' : 'workshop')
  }

  // Initialize from sessionStorage (called once)
  const initializeMode = () => {
    if (isInitialized.value) return

    const stored = safeSessionStorage.get(STORAGE_KEY)
    if (stored && (stored === 'workshop' || stored === 'office')) {
      mode.value = stored
      hasUserExplicitlyChosen.value = true
    }

    isInitialized.value = true
  }

  // Initialize on mount
  onMounted(() => {
    initializeMode()
  })

  // Also initialize immediately if not in component context
  if (!isInitialized.value) {
    initializeMode()
  }

  return {
    activeMode,
    isWorkshopMode,
    isOfficeMode,
    defaultMode,
    hasUserExplicitlyChosen: computed(() => hasUserExplicitlyChosen.value),
    setMode,
    toggleMode,
  }
}
