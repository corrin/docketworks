import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import SectionForm from '@/components/SectionForm.vue'

const { clientsAllList } = vi.hoisted(() => ({
  clientsAllList: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    clients_all_list: clientsAllList,
  },
}))

vi.mock('@/composables/useSettingsSchema', () => ({
  useSettingsSchema: () => ({
    getFieldsForSection: () => [
      {
        key: 'shop_client',
        label: 'Shop Client',
        type: 'client',
        required: true,
        help_text: 'Internal client used for tracking shop work.',
        section: 'setup',
        icon: 'span',
        readOnly: false,
      },
    ],
    getSpecialHandler: () => undefined,
  }),
}))

describe('SectionForm', () => {
  it('renders client fields as a selector backed by generated client data', async () => {
    clientsAllList.mockResolvedValue([
      { id: '00000000-0000-0000-0000-000000000001', name: 'Demo Company Shop' },
      { id: '11111111-1111-1111-1111-111111111111', name: 'Acme Ltd' },
    ])

    const wrapper = mount(SectionForm, {
      props: {
        section: 'setup',
        modelValue: {
          shop_client: '00000000-0000-0000-0000-000000000001',
        },
      },
    })

    await flushPromises()

    const selector = wrapper.get('[data-automation-id="SectionForm-setup-field-shop_client"]')
    expect(selector.element.tagName).toBe('SELECT')
    expect(selector.text()).toContain('Demo Company Shop')
    expect(selector.text()).toContain('Acme Ltd')

    await selector.setValue('11111111-1111-1111-1111-111111111111')

    const updates = wrapper.emitted('update:modelValue')
    expect(updates?.at(-1)).toEqual([
      {
        shop_client: '11111111-1111-1111-1111-111111111111',
      },
    ])
  })
})
