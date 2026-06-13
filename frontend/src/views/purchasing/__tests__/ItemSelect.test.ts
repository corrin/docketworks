import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const { logSearchResultClick } = vi.hoisted(() => ({
  logSearchResultClick: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    purchasing_stock_search_retrieve: vi.fn(),
  },
}))

vi.mock('@/utils/string-formatting', () => ({
  formatCurrency: (n: number | null | undefined) => `$${(n ?? 0).toFixed(2)}`,
}))

vi.mock('@/services/searchTelemetry.service', () => ({
  logSearchResultClick,
}))

vi.mock('../../../components/ui/popover', () => ({
  Popover: {
    name: 'Popover',
    props: ['open'],
    emits: ['update:open'],
    template: '<div class="ui-popover"><slot /></div>',
  },
  PopoverTrigger: {
    name: 'PopoverTrigger',
    template: '<div class="ui-popover-trigger"><slot /></div>',
  },
  PopoverContent: {
    name: 'PopoverContent',
    template: '<div class="ui-popover-content"><slot /></div>',
  },
}))

vi.mock('../../../components/ui/button', () => ({
  Button: {
    name: 'Button',
    props: ['disabled', 'type', 'variant'],
    template: '<button :disabled="disabled" :type="type || \'button\'"><slot /></button>',
  },
}))

vi.mock('../../../components/ui/badge', () => ({
  Badge: { template: '<span class="badge"><slot /></span>' },
}))

vi.mock('../../../components/ui/input', () => ({
  Input: {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template:
      '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
}))

import ItemSelect from '../ItemSelect.vue'
import { api } from '@/api/client'
import { useStockStore } from '@/stores/stockStore'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { labourItemId, type JobLabourRate } from '@/utils/labourRates'
import type { z } from 'zod'
import type { schemas } from '@/api/generated/api'

type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>

const purchasing_stock_search_retrieve = api.purchasing_stock_search_retrieve as ReturnType<
  typeof vi.fn
>

const WORKSHOP_SUBTYPE = '11111111-1111-4111-8111-111111111111'
const ADMIN_SUBTYPE = '22222222-2222-4222-8222-222222222222'

const labourRates: JobLabourRate[] = [
  {
    id: 'aaaaaaaa-0000-4000-8000-000000000001',
    labour_subtype: WORKSHOP_SUBTYPE,
    labour_subtype_name: 'Workshop',
    is_workshop: true,
    charge_out_rate: 105,
  },
  {
    id: 'aaaaaaaa-0000-4000-8000-000000000002',
    labour_subtype: ADMIN_SUBTYPE,
    labour_subtype_name: 'Admin',
    is_workshop: false,
    charge_out_rate: 90,
  },
]

function setCompanyWageRate(wageRate: number) {
  const defaultsStore = useCompanyDefaultsStore()
  defaultsStore.companyDefaults = { wage_rate: wageRate } as unknown as CompanyDefaults
}

function buildStockItem(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: over.id ?? 'stock-1',
    job_id: null,
    item_code: over.item_code ?? 'CODE',
    description:
      over.description ?? 'A very long stainless steel description that should not be truncated',
    quantity: over.quantity ?? 5,
    unit_cost: over.unit_cost ?? 10,
    unit_revenue: over.unit_revenue ?? 15,
    metal_type: over.metal_type ?? 'stainless steel',
    alloy: over.alloy ?? '304',
    specifics: over.specifics ?? '5mm sheet',
    times_used: over.times_used ?? 12,
    location: over.location ?? '',
    is_active: true,
    source: 'manual',
    date: '2026-05-09T00:00:00Z',
    ...over,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
})

describe('ItemSelect server-side search and rendering', () => {
  it('renders one blue labour option per job labour rate in estimate context', async () => {
    const store = useStockStore()
    store.items = [buildStockItem({ id: 's1', times_used: 9 })]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate', labourRates },
    })
    await flushPromises()

    const labourOptions = wrapper.findAll('[data-automation-id^="ItemSelect-option-labour-"]')
    expect(labourOptions).toHaveLength(2)
    expect(labourOptions[0].attributes('data-automation-id')).toBe(
      `ItemSelect-option-labour-${WORKSHOP_SUBTYPE}`,
    )
    expect(labourOptions[1].attributes('data-automation-id')).toBe(
      `ItemSelect-option-labour-${ADMIN_SUBTYPE}`,
    )
    expect(labourOptions[0].text()).toContain('Workshop')
    expect(labourOptions[0].classes()).toContain('bg-blue-50')
    expect(labourOptions[0].find('.font-medium').classes()).toContain('text-blue-900')
    // Every labour option carries an explicit LABOUR tag (bottom-left slot)
    for (const option of labourOptions) {
      expect(option.find('[data-automation-id="ItemSelect-labour-tag"]').text()).toBe('LABOUR')
    }
    // No stock rendered without an active (>=3 char) query
    expect(wrapper.find('[data-automation-id="ItemSelect-option-CODE"]').exists()).toBe(false)
  })

  it('pins labour options above stock results', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [buildStockItem({ id: 's1', description: 'Workbench top' })],
      count: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    })

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate', labourRates },
    })
    await flushPromises()

    await wrapper.find('input').setValue('work')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    const options = wrapper.findAll('[data-automation-id^="ItemSelect-option-"]')
    expect(options).toHaveLength(2)
    expect(options[0].attributes('data-automation-id')).toBe(
      `ItemSelect-option-labour-${WORKSHOP_SUBTYPE}`,
    )
    expect(options[1].attributes('data-automation-id')).toBe('ItemSelect-option-CODE')

    vi.useRealTimers()
  })

  it('emits the full labour payload with the per-subtype rate on selection', async () => {
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])
    setCompanyWageRate(32)

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate', labourRates },
    })
    await flushPromises()

    wrapper.vm.handleSelectedValue(labourItemId(ADMIN_SUBTYPE))

    const selectedItemEvents = wrapper.emitted('selectedItem')
    expect(selectedItemEvents).toBeTruthy()
    const payload = selectedItemEvents?.at(-1)?.[0] as Record<string, unknown>
    expect(payload).toMatchObject({
      type: 'labour',
      id: labourItemId(ADMIN_SUBTYPE),
      labour_subtype: ADMIN_SUBTYPE,
      description: 'Admin',
      unit_cost: 32,
      unit_rev: 90,
      unit_revenue: 90,
    })
    expect(payload).not.toHaveProperty('value')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([labourItemId(ADMIN_SUBTYPE)])
    expect(wrapper.emitted('update:description')?.at(-1)).toEqual(['Admin'])
    expect(wrapper.emitted('update:unit_cost')?.at(-1)).toEqual([32])
    expect(wrapper.emitted('update:kind')?.at(-1)).toEqual(['time'])
  })

  it('filters labour options by name at short query lengths without a server call', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate', labourRates },
    })
    await flushPromises()

    await wrapper.find('input').setValue('ad')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()
    const labourOptions = wrapper.findAll('[data-automation-id^="ItemSelect-option-labour-"]')
    expect(labourOptions).toHaveLength(1)
    expect(labourOptions[0].text()).toContain('Admin')

    vi.useRealTimers()
  })

  it("matches every labour option when searching for 'labour'", async () => {
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate', labourRates },
    })
    await flushPromises()

    for (const term of ['lab', 'LABOUR']) {
      await wrapper.find('input').setValue(term)
      await flushPromises()
      expect(
        wrapper.findAll('[data-automation-id^="ItemSelect-option-labour-"]'),
        `term: ${term}`,
      ).toHaveLength(labourRates.length)
    }
  })

  it('shows the subtype name in blue on the trigger for a labour modelValue', async () => {
    const wrapper = mount(ItemSelect, {
      props: {
        modelValue: labourItemId(WORKSHOP_SUBTYPE),
        tabKind: 'estimate',
        labourRates,
      },
    })
    await flushPromises()

    const triggerText = wrapper.find('.truncate')
    expect(triggerText.text()).toBe('Workshop')
    expect(triggerText.classes()).toContain('text-blue-800')
    expect(triggerText.classes()).toContain('font-medium')
  })

  it("falls back to 'Labour' on the trigger for an unknown labour subtype", async () => {
    const wrapper = mount(ItemSelect, {
      props: {
        modelValue: labourItemId('99999999-9999-4999-8999-999999999999'),
        tabKind: 'estimate',
        labourRates,
      },
    })
    await flushPromises()

    expect(wrapper.find('.truncate').text()).toBe('Labour')
  })

  it('renders no labour options on the actual tab', async () => {
    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'actual', labourRates },
    })
    await flushPromises()

    expect(wrapper.findAll('[data-automation-id^="ItemSelect-option-labour-"]')).toHaveLength(0)
  })

  it('renders no labour options when the job has no labour rates', async () => {
    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate', labourRates: [] },
    })
    await flushPromises()

    expect(wrapper.findAll('[data-automation-id^="ItemSelect-option-labour-"]')).toHaveLength(0)
  })

  it('focuses the search field when opened', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])

    const wrapper = mount(ItemSelect, {
      attachTo: document.body,
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    wrapper.vm.handleOpenUpdate(true)
    await flushPromises()
    await vi.runOnlyPendingTimersAsync()

    expect(document.activeElement).toBe(wrapper.find('input').element)
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('focuses the search field when mounted already open', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])

    const wrapper = mount(ItemSelect, {
      attachTo: document.body,
      props: { modelValue: null, open: true, tabKind: 'estimate' },
    })
    await flushPromises()
    await vi.runOnlyPendingTimersAsync()

    expect(document.activeElement).toBe(wrapper.find('input').element)
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('lets Escape leave the search field for the select to close', async () => {
    const wrapper = mount(ItemSelect, {
      attachTo: document.body,
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    const bubbled = vi.fn()
    document.body.addEventListener('keydown', bubbled)
    await wrapper.find('input').trigger('keydown', { key: 'Escape' })

    expect(bubbled).toHaveBeenCalledTimes(1)
    document.body.removeEventListener('keydown', bubbled)
    wrapper.unmount()
  })

  it('keeps search typing inside the search field', async () => {
    const wrapper = mount(ItemSelect, {
      attachTo: document.body,
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    const bubbled = vi.fn()
    document.body.addEventListener('keydown', bubbled)
    await wrapper.find('input').trigger('keydown', { key: 's' })

    expect(bubbled).not.toHaveBeenCalled()
    document.body.removeEventListener('keydown', bubbled)
    wrapper.unmount()
  })

  it('renders the full description, structured-fields signature, and usage count from server results', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [buildStockItem({ id: 's1', times_used: 9 })],
      count: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    })

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    const input = wrapper.find('input')
    await input.setValue('steel')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    const stockOption = wrapper.find('[data-automation-id="ItemSelect-option-CODE"]')
    expect(stockOption.exists()).toBe(true)

    const descriptionDiv = stockOption.find('.font-medium')
    expect(descriptionDiv.classes()).toContain('whitespace-normal')
    expect(descriptionDiv.classes()).toContain('break-words')
    expect(descriptionDiv.classes()).not.toContain('truncate')
    expect(descriptionDiv.text()).toBe(
      'A very long stainless steel description that should not be truncated',
    )

    const signature = stockOption.find('[data-automation-id="ItemSelect-variant-signature"]')
    expect(signature.exists()).toBe(true)
    expect(signature.text()).toBe('stainless steel · 304 · 5mm sheet')

    const timesUsed = stockOption.find('[data-automation-id="ItemSelect-times-used"]')
    expect(timesUsed.exists()).toBe(true)
    expect(timesUsed.text()).toBe('Used 9 times')

    vi.useRealTimers()
  })

  it('debounces input and calls the stock search endpoint after settle', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [buildStockItem({ id: 'r1', description: 'Server result' })],
      count: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    })

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    const input = wrapper.find('input')
    await input.setValue('sta')
    await input.setValue('stai')
    await input.setValue('stainless')

    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(purchasing_stock_search_retrieve).toHaveBeenCalledTimes(1)
    expect(purchasing_stock_search_retrieve).toHaveBeenCalledWith({
      queries: { q: 'stainless', page: 1, page_size: 50 },
    })

    vi.useRealTimers()
  })

  it('logs selected stock search result with visible rank', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [buildStockItem({ id: 's1', item_code: 'CODE' })],
      count: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    })

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    await wrapper.find('input').setValue('sheet')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    await wrapper.find('[data-automation-id="ItemSelect-option-CODE"]').trigger('click')

    expect(logSearchResultClick).toHaveBeenCalledWith(
      expect.objectContaining({
        domain: 'stock',
        query: 'sheet',
        selectedResultId: 's1',
        selectedLabel: 'CODE',
        selectedRank: 1,
        resultCount: 1,
        source: 'item_select',
      }),
    )

    vi.useRealTimers()
  })

  it('keeps sub-3-character queries local and does not render the full stock cache', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = [
      buildStockItem({ id: 's1', description: 'Steel sheet' }),
      buildStockItem({ id: 's2', description: 'Aluminium bar' }),
    ]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate', labourRates },
    })
    await flushPromises()

    const input = wrapper.find('input')
    await input.setValue('st')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()
    // 'st' matches no labour subtype name and stock search is not active yet
    expect(wrapper.findAll('[data-automation-id^="ItemSelect-option-labour-"]')).toHaveLength(0)
    expect(wrapper.find('[data-automation-id="ItemSelect-option-CODE"]').exists()).toBe(false)

    vi.useRealTimers()
  })

  it('suppresses the noisy unspecified metal_type in the metadata line', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [
        buildStockItem({
          id: 's1',
          metal_type: 'unspecified',
          alloy: '316',
          specifics: '1.5mm sheet',
          times_used: 4,
        }),
      ],
      count: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    })

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    const input = wrapper.find('input')
    await input.setValue('sheet')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    const stockOption = wrapper.find('[data-automation-id="ItemSelect-option-CODE"]')
    const signature = stockOption.find('[data-automation-id="ItemSelect-variant-signature"]')
    expect(signature.exists()).toBe(true)
    expect(signature.text()).toBe('316 · 1.5mm sheet')
    expect(stockOption.text()).not.toContain('unspecified')

    vi.useRealTimers()
  })
})
