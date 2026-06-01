import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SaveStatusIndicator from '@/components/shared/SaveStatusIndicator.vue'
import { useSaveStatusStore } from '@/stores/saveStatus'

describe('SaveStatusIndicator', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('stays visually empty when no save source is active', () => {
    const wrapper = mount(SaveStatusIndicator)

    expect(wrapper.text()).toBe('')
  })

  it('collapses pending and in-flight work into Saving', async () => {
    const store = useSaveStatusStore()
    const wrapper = mount(SaveStatusIndicator)

    store.setSource('job', 'pending')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Saving...')

    store.setSource('timesheet', 'saving')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Saving...')
  })

  it('shows Saved only when no source is still saving', async () => {
    const store = useSaveStatusStore()
    const wrapper = mount(SaveStatusIndicator)

    store.setSource('job', 'saved')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Saved')
  })

  it('shows save failures ahead of active saves', async () => {
    const store = useSaveStatusStore()
    const wrapper = mount(SaveStatusIndicator)

    store.setSource('job', 'error', 'Save failed')
    store.setSource('timesheet', 'saving')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Save failed')
  })

  it('keeps the error label available on compact layouts', async () => {
    const store = useSaveStatusStore()
    const wrapper = mount(SaveStatusIndicator)

    store.setSource('job', 'error', 'Save failed')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[aria-label="Save failed"]').exists()).toBe(true)
  })
})
