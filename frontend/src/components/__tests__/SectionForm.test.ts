import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import SectionForm from '@/components/SectionForm.vue'

const { companiesAllList } = vi.hoisted(() => ({
  companiesAllList: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    companies_all_list: companiesAllList,
  },
}))

vi.mock('@/composables/useSettingsSchema', () => ({
  useSettingsSchema: () => ({
    getFieldsForSection: () => [
      {
        key: 'shop_company',
        label: 'Shop Company',
        type: 'company',
        required: true,
        help_text: 'Internal company used for tracking shop work.',
        section: 'setup',
        icon: 'span',
        readOnly: false,
      },
    ],
    getSpecialHandler: () => undefined,
  }),
  REMOVED_SETTING_KEYS: new Set<string>(),
  omitRemovedSettings: <T extends Record<string, unknown>>(form: T): T => form,
}))

describe('SectionForm', () => {
  it('renders company fields as a selector backed by generated company data', async () => {
    companiesAllList.mockResolvedValue([
      { id: '00000000-0000-0000-0000-000000000001', name: 'Demo Company Shop' },
      { id: '11111111-1111-1111-1111-111111111111', name: 'Acme Ltd' },
    ])

    const wrapper = mount(SectionForm, {
      props: {
        section: 'setup',
        modelValue: {
          shop_company: '00000000-0000-0000-0000-000000000001',
        },
      },
    })

    await flushPromises()

    const selector = wrapper.get('[data-automation-id="SectionForm-setup-field-shop_company"]')
    expect(selector.element.tagName).toBe('SELECT')
    expect(selector.text()).toContain('Demo Company Shop')
    expect(selector.text()).toContain('Acme Ltd')

    await selector.setValue('11111111-1111-1111-1111-111111111111')

    const updates = wrapper.emitted('update:modelValue')
    expect(updates?.at(-1)).toEqual([
      {
        shop_company: '11111111-1111-1111-1111-111111111111',
      },
    ])
  })

  it('does not mutate the object passed as modelValue when a field is edited', async () => {
    companiesAllList.mockResolvedValue([
      { id: '00000000-0000-0000-0000-000000000001', name: 'Demo Company Shop' },
      { id: '11111111-1111-1111-1111-111111111111', name: 'Acme Ltd' },
    ])

    const modelValue = {
      shop_company: '00000000-0000-0000-0000-000000000001',
    }

    const wrapper = mount(SectionForm, {
      props: {
        section: 'setup',
        modelValue,
      },
    })

    await flushPromises()

    const selector = wrapper.get('[data-automation-id="SectionForm-setup-field-shop_company"]')
    await selector.setValue('11111111-1111-1111-1111-111111111111')

    // The edit must be emitted, never applied in place to the prop object.
    expect(modelValue.shop_company).toBe('00000000-0000-0000-0000-000000000001')
  })
})
