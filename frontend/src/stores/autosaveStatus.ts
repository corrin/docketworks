import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type AutosaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export interface AutosaveSourceStatus {
  state: AutosaveState
  message?: string
  updatedAt: number
}

const ACTIVE_STATES = new Set<AutosaveState>(['pending', 'saving'])

export const useAutosaveStatusStore = defineStore('autosaveStatus', () => {
  const sources = ref<Record<string, AutosaveSourceStatus>>({})

  const setSource = (source: string, state: AutosaveState, message?: string): void => {
    if (state === 'idle') {
      clearSource(source)
      return
    }

    sources.value = {
      ...sources.value,
      [source]: {
        state,
        message,
        updatedAt: Date.now(),
      },
    }
  }

  const clearSource = (source: string): void => {
    if (!(source in sources.value)) return
    const next = { ...sources.value }
    delete next[source]
    sources.value = next
  }

  const clearAll = (): void => {
    sources.value = {}
  }

  const aggregate = computed<AutosaveSourceStatus | null>(() => {
    const values = Object.values(sources.value)
    if (!values.length) return null

    const newest = (states: AutosaveState[]) =>
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
