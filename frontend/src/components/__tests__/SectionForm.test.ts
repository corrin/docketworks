import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SectionForm from '@/components/SectionForm.vue'

const { companiesAllList, xeroBrandingThemesList, settingsFields, toastError } = vi.hoisted(() => ({
  companiesAllList: vi.fn(),
  xeroBrandingThemesList: vi.fn(),
  settingsFields: [] as Array<Record<string, unknown>>,
  toastError: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    companies_all_list: companiesAllList,
    xero_branding_themes_list: xeroBrandingThemesList,
  },
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: toastError,
    success: vi.fn(),
  },
}))

vi.mock('@/composables/useSettingsSchema', () => ({
  useSettingsSchema: () => ({
    getFieldsForSection: () => settingsFields,
    getSpecialHandler: () => undefined,
  }),
  REMOVED_SETTING_KEYS: new Set<string>(),
  omitRemovedSettings: <T extends Record<string, unknown>>(form: T): T => form,
}))

describe('SectionForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    settingsFields.splice(0, settingsFields.length, {
      key: 'shop_company',
      label: 'Shop Company',
      type: 'company',
      required: true,
      help_text: 'Internal company used for tracking shop work.',
      section: 'setup',
      icon: 'span',
      readOnly: false,
    })
  })

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

  it('shows automatic initialization and allows selecting a live Xero branding theme', async () => {
    settingsFields.splice(0, settingsFields.length, {
      key: 'xero_sales_branding_theme_id',
      label: 'Sales Branding Theme',
      type: 'xero_branding_theme',
      required: false,
      help_text: 'Branding theme used for sales documents.',
      section: 'xero',
      icon: 'span',
      readOnly: false,
    })
    xeroBrandingThemesList.mockResolvedValue([
      {
        branding_theme_id: '22222222-2222-2222-2222-222222222222',
        name: 'Standard',
        is_default: true,
      },
      {
        branding_theme_id: '33333333-3333-3333-3333-333333333333',
        name: 'Terms Footer',
        is_default: false,
      },
    ])

    const wrapper = mount(SectionForm, {
      props: {
        section: 'xero',
        modelValue: { xero_sales_branding_theme_id: null },
      },
    })
    await flushPromises()

    const selector = wrapper.get(
      '[data-automation-id="SectionForm-xero-field-xero_sales_branding_theme_id"]',
    )
    expect(selector.element.tagName).toBe('SELECT')
    expect(selector.text()).toContain('Standard (Xero default)')
    expect(selector.text()).toContain('Terms Footer')
    expect(selector.text()).toContain('Not configured — first document will use Standard')
    expect(selector.find('option[value=""]').attributes('disabled')).toBeDefined()
    expect(selector.element.closest('label')?.className).toContain('md:col-span-2')

    await selector.setValue('33333333-3333-3333-3333-333333333333')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([
      { xero_sales_branding_theme_id: '33333333-3333-3333-3333-333333333333' },
    ])
  })

  it('preserves a configured branding theme that Xero no longer returns', async () => {
    settingsFields.splice(0, settingsFields.length, {
      key: 'xero_sales_branding_theme_id',
      label: 'Sales Branding Theme',
      type: 'xero_branding_theme',
      required: false,
      help_text: '',
      section: 'xero',
      icon: 'span',
      readOnly: false,
    })
    xeroBrandingThemesList.mockResolvedValue([
      {
        branding_theme_id: '22222222-2222-2222-2222-222222222222',
        name: 'Current Default',
        is_default: true,
      },
    ])
    const unavailableId = '44444444-4444-4444-4444-444444444444'

    const wrapper = mount(SectionForm, {
      props: {
        section: 'xero',
        modelValue: { xero_sales_branding_theme_id: unavailableId },
      },
    })
    await flushPromises()

    const selector = wrapper.get(
      '[data-automation-id="SectionForm-xero-field-xero_sales_branding_theme_id"]',
    )
    expect((selector.element as HTMLSelectElement).value).toBe(unavailableId)
    expect(selector.text()).toContain(`Unavailable theme (${unavailableId})`)
    expect((selector.element as HTMLSelectElement).disabled).toBe(false)
  })

  it('disables the selector when Xero returns no branding themes', async () => {
    settingsFields.splice(0, settingsFields.length, {
      key: 'xero_sales_branding_theme_id',
      label: 'Sales Branding Theme',
      type: 'xero_branding_theme',
      required: false,
      help_text: '',
      section: 'xero',
      icon: 'span',
      readOnly: false,
    })
    xeroBrandingThemesList.mockResolvedValue([])

    const wrapper = mount(SectionForm, {
      props: {
        section: 'xero',
        modelValue: { xero_sales_branding_theme_id: null },
      },
    })
    await flushPromises()

    const selector = wrapper.get(
      '[data-automation-id="SectionForm-xero-field-xero_sales_branding_theme_id"]',
    )
    expect((selector.element as HTMLSelectElement).disabled).toBe(true)
    expect(
      wrapper
        .get('[data-automation-id="SectionForm-xero-field-xero_sales_branding_theme_id-empty"]')
        .text(),
    ).toContain('No branding themes are available')
  })

  it('disables the branding theme selector and explains a Xero loading failure', async () => {
    settingsFields.splice(0, settingsFields.length, {
      key: 'xero_sales_branding_theme_id',
      label: 'Sales Branding Theme',
      type: 'xero_branding_theme',
      required: false,
      help_text: '',
      section: 'xero',
      icon: 'span',
      readOnly: false,
    })
    xeroBrandingThemesList.mockRejectedValue(new Error('Xero unavailable'))
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    const wrapper = mount(SectionForm, {
      props: {
        section: 'xero',
        modelValue: { xero_sales_branding_theme_id: null },
      },
    })
    await flushPromises()

    const selector = wrapper.get(
      '[data-automation-id="SectionForm-xero-field-xero_sales_branding_theme_id"]',
    )
    expect((selector.element as HTMLSelectElement).disabled).toBe(true)
    expect(
      wrapper
        .get('[data-automation-id="SectionForm-xero-field-xero_sales_branding_theme_id-error"]')
        .text(),
    ).toContain('Could not load branding themes from Xero')
    expect(toastError).toHaveBeenCalledWith('Failed to load Xero branding themes')
  })
})
