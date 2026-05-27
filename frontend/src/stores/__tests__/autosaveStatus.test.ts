import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAutosaveStatusStore } from '@/stores/autosaveStatus'

describe('autosaveStatus store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useRealTimers()
  })

  it('shows active saves before saved state', () => {
    const store = useAutosaveStatusStore()

    store.setSource('job', 'saved')
    store.setSource('timesheet', 'saving')

    expect(store.aggregate?.state).toBe('saving')
    expect(store.hasActiveSave).toBe(true)
  })

  it('keeps errors visible until the failing source is cleared or retried', () => {
    const store = useAutosaveStatusStore()

    store.setSource('job', 'error', 'Save failed')
    store.setSource('timesheet', 'saving')

    expect(store.aggregate?.state).toBe('error')
    expect(store.aggregate?.message).toBe('Save failed')

    store.clearSource('job')

    expect(store.aggregate?.state).toBe('saving')
  })

  it('clears idle sources', () => {
    const store = useAutosaveStatusStore()

    store.setSource('job', 'saved')
    store.setSource('job', 'idle')

    expect(store.aggregate).toBeNull()
  })
})
