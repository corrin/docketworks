import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSaveStatusStore } from '@/stores/saveStatus'

describe('saveStatus store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows active saves before saved state', () => {
    const store = useSaveStatusStore()

    store.setSource('job', 'saved')
    store.setSource('timesheet', 'saving')

    expect(store.aggregate?.state).toBe('saving')
    expect(store.hasActiveSave).toBe(true)
  })

  it('keeps errors visible until the failing source is cleared or retried', () => {
    const store = useSaveStatusStore()

    store.setSource('job', 'error', 'Save failed')
    store.setSource('timesheet', 'saving')

    expect(store.aggregate?.state).toBe('error')
    expect(store.aggregate?.message).toBe('Save failed')

    store.clearSource('job')

    expect(store.aggregate?.state).toBe('saving')
  })

  it('clears idle sources', () => {
    const store = useSaveStatusStore()

    store.setSource('job', 'saved')
    store.setSource('job', 'idle')

    expect(store.aggregate).toBeNull()
  })

  it('briefly shows saved and then clears it', () => {
    const store = useSaveStatusStore()

    store.setSource('job', 'saved')

    expect(store.aggregate?.state).toBe('saved')

    vi.advanceTimersByTime(1999)
    expect(store.aggregate?.state).toBe('saved')

    vi.advanceTimersByTime(1)
    expect(store.aggregate).toBeNull()
  })

  it('does not clear a newer source state with an old saved timer', () => {
    const store = useSaveStatusStore()

    store.setSource('job', 'saved')
    vi.advanceTimersByTime(1000)
    store.setSource('job', 'saving')
    vi.advanceTimersByTime(1000)

    expect(store.aggregate?.state).toBe('saving')
  })

  it('does not auto-clear errors', () => {
    const store = useSaveStatusStore()

    store.setSource('job', 'error', 'Save failed')
    vi.advanceTimersByTime(5000)

    expect(store.aggregate?.state).toBe('error')
    expect(store.aggregate?.message).toBe('Save failed')
  })
})
