import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

import AIProviderFormModal from '../AIProviderFormModal.vue'

// The modal's Dialog and Select primitives (reka-ui) render via Teleport,
// which is irrelevant to the submit payload under test; stub them to plain
// pass-through markup so the form inputs are queryable directly.
const stubs = {
  Dialog: { template: '<div><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  DialogFooter: { template: '<div><slot /></div>' },
  Select: { template: '<div><slot /></div>' },
  SelectTrigger: { template: '<div><slot /></div>' },
  SelectContent: { template: '<div><slot /></div>' },
  SelectItem: { template: '<div><slot /></div>' },
  SelectValue: { template: '<div />' },
  Switch: { template: '<input type="checkbox" />' },
  Button: { template: '<button><slot /></button>' },
}

const existingProvider = {
  id: 7,
  name: 'Gemini prod',
  provider_type: 'Gemini' as const,
  model_name: 'gemini-flash-latest',
  default: true,
}

// vee-validate resolves the validation schema across macrotasks, so a
// microtask flush alone lands before the submit handler runs. Poll for the
// emit rather than guessing a delay.
async function submitAndGetSaved(wrapper: ReturnType<typeof mount>) {
  await wrapper.find('form').trigger('submit')
  await vi.waitUntil(() => wrapper.emitted('save'))
  await flushPromises()
  return wrapper.emitted('save')?.at(-1)?.[0] as Record<string, unknown>
}

describe('AIProviderFormModal model_name', () => {
  it('emits null when an existing model name is cleared, so it can be unset', async () => {
    const wrapper = mount(AIProviderFormModal, {
      props: { provider: existingProvider },
      global: { stubs },
    })

    await wrapper.find('#model_name').setValue('')

    // Omitting the key would leave the stored name in place: PATCH only
    // writes fields it is sent.
    expect(await submitAndGetSaved(wrapper)).toHaveProperty('model_name', null)
  })

  it('emits null rather than "" when creating a provider with no model name', async () => {
    const wrapper = mount(AIProviderFormModal, {
      props: { provider: null },
      global: { stubs },
    })

    await wrapper.find('#name').setValue('New provider')
    await wrapper.find('#api_key').setValue('sk-test')

    // The column's unset is NULL and the serializer rejects "" outright.
    expect(await submitAndGetSaved(wrapper)).toHaveProperty('model_name', null)
  })

  it('emits the entered model name unchanged', async () => {
    const wrapper = mount(AIProviderFormModal, {
      props: { provider: existingProvider },
      global: { stubs },
    })

    await wrapper.find('#model_name').setValue('gemini-pro-latest')

    expect(await submitAndGetSaved(wrapper)).toHaveProperty('model_name', 'gemini-pro-latest')
  })
})
