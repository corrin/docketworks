import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AutosaveStatusIndicator from '@/components/shared/AutosaveStatusIndicator.vue'
import { useAutosaveStatusStore } from '@/stores/autosaveStatus'

describe('AutosaveStatusIndicator', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('stays visually empty when no autosave source is active', () => {
    const wrapper = mount(AutosaveStatusIndicator)

    expect(wrapper.text()).toBe('')
  })

  it('collapses pending and in-flight work into Saving', async () => {
    const store = useAutosaveStatusStore()
    const wrapper = mount(AutosaveStatusIndicator)

    store.setSource('job', 'pending')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Saving...')

    store.setSource('timesheet', 'saving')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Saving...')
  })

  it('shows Saved only when no source is still saving', async () => {
    const store = useAutosaveStatusStore()
    const wrapper = mount(AutosaveStatusIndicator)

    store.setSource('job', 'saved')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Saved')
  })

  it('shows save failures ahead of active saves', async () => {
    const store = useAutosaveStatusStore()
    const wrapper = mount(AutosaveStatusIndicator)

    store.setSource('job', 'error', 'Save failed')
    store.setSource('timesheet', 'saving')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Save failed')
  })
})
