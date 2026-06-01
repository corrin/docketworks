import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export interface SaveSourceStatus {
  state: SaveState
  message?: string
  updatedAt: number
}

const ACTIVE_STATES = new Set<SaveState>(['pending', 'saving'])
const SAVED_CLEAR_DELAY_MS = 2000

export const useSaveStatusStore = defineStore('saveStatus', () => {
  const sources = ref<Record<string, SaveSourceStatus>>({})
  const clearTimers = new Map<string, ReturnType<typeof setTimeout>>()

  const clearSavedTimer = (source: string): void => {
    const timer = clearTimers.get(source)
    if (!timer) return
    clearTimeout(timer)
    clearTimers.delete(source)
  }

  const scheduleSavedClear = (source: string, updatedAt: number): void => {
    clearSavedTimer(source)
    const timer = setTimeout(() => {
      clearTimers.delete(source)
      const current = sources.value[source]
      if (!current || current.state !== 'saved' || current.updatedAt !== updatedAt) return
      clearSource(source)
    }, SAVED_CLEAR_DELAY_MS)
    clearTimers.set(source, timer)
  }

  const setSource = (source: string, state: SaveState, message?: string): void => {
    if (state === 'idle') {
      clearSource(source)
      return
    }

    clearSavedTimer(source)
    const updatedAt = Date.now()
    sources.value = {
      ...sources.value,
      [source]: {
        state,
        message,
        updatedAt,
      },
    }

    if (state === 'saved') {
      scheduleSavedClear(source, updatedAt)
    }
  }

  const clearSource = (source: string): void => {
    clearSavedTimer(source)
    if (!(source in sources.value)) return
    const next = { ...sources.value }
    delete next[source]
    sources.value = next
  }

  const clearAll = (): void => {
    for (const timer of clearTimers.values()) {
      clearTimeout(timer)
    }
    clearTimers.clear()
    sources.value = {}
  }

  const aggregate = computed<SaveSourceStatus | null>(() => {
    const values = Object.values(sources.value)
    if (!values.length) return null

    const newest = (states: SaveState[]) =>
      values
        .filter((source) => states.includes(source.state))
        .sort((left, right) => right.updatedAt - left.updatedAt)[0] ?? null

    return (
      newest(['error']) ?? newest(['saving', 'pending']) ?? newest(['saved']) ?? newest(['idle'])
    )
  })

  const hasActiveSave = computed(() =>
    Object.values(sources.value).some((source) => ACTIVE_STATES.has(source.state)),
  )

  return {
    sources,
    aggregate,
    hasActiveSave,
    setSource,
    clearSource,
    clearAll,
  }
})
