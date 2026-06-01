import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSaveFeedback } from '@/composables/useSaveFeedback'
import { useSaveStatusStore } from '@/stores/saveStatus'
import { toast } from 'vue-sonner'

vi.mock('vue-sonner', () => ({
  toast: {
    dismiss: vi.fn(),
    error: vi.fn(),
  },
}))

describe('useSaveFeedback', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('updates a source through the save lifecycle', () => {
    const feedback = useSaveFeedback('job')
    const store = useSaveStatusStore()

    feedback.pending()
    expect(store.aggregate?.state).toBe('pending')

    feedback.saving()
    expect(store.aggregate?.state).toBe('saving')

    feedback.saved()
    expect(store.aggregate?.state).toBe('saved')

    feedback.clear()
    expect(store.aggregate).toBeNull()
  })

  it('keeps errors persistent until the source is cleared', () => {
    const feedback = useSaveFeedback('job')
    const store = useSaveStatusStore()

    feedback.error('Save failed')

    expect(store.aggregate?.state).toBe('error')
    expect(store.aggregate?.message).toBe('Save failed')
    expect(toast.error).toHaveBeenCalledWith('Save failed', {
      id: 'save-error:job',
      duration: 8000,
    })

    feedback.clear()
    expect(store.aggregate).toBeNull()
    expect(toast.dismiss).toHaveBeenCalledWith('save-error:job')
  })

  it('can update global error state without showing a helper toast', () => {
    const feedback = useSaveFeedback('job', { toastErrors: false })
    const store = useSaveStatusStore()

    feedback.error('Failed to consume stock.')

    expect(store.aggregate?.state).toBe('error')
    expect(store.aggregate?.message).toBe('Failed to consume stock.')
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('can clear the source on component unmount', () => {
    const Component = defineComponent({
      setup() {
        const feedback = useSaveFeedback('job', { clearOnUnmount: true })
        feedback.saving()
        return {}
      },
      template: '<div />',
    })
    const store = useSaveStatusStore()
    const wrapper = mount(Component)

    expect(store.aggregate?.state).toBe('saving')

    wrapper.unmount()

    expect(store.aggregate).toBeNull()
  })
})
