import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    purchasing_stock_search_retrieve: vi.fn(),
  },
}))

vi.mock('@/utils/string-formatting', () => ({
  formatCurrency: (n: number | null | undefined) => `$${(n ?? 0).toFixed(2)}`,
}))

vi.mock('../../../components/ui/select', () => ({
  Select: { template: '<div class="ui-select"><slot /></div>' },
  SelectTrigger: { template: '<div class="ui-select-trigger"><slot /></div>' },
  SelectValue: { template: '<div />' },
  SelectContent: { template: '<div class="ui-select-content"><slot /></div>' },
  SelectItem: {
    props: ['value'],
    template: '<div class="ui-select-item" :data-value="value" role="option"><slot /></div>',
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

const purchasing_stock_search_retrieve = api.purchasing_stock_search_retrieve as ReturnType<
  typeof vi.fn
>

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
  it('renders the labour option by default in estimate context', async () => {
    const store = useStockStore()
    store.items = [buildStockItem({ id: 's1', times_used: 9 })]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    const labourOption = wrapper.find('[data-value="__labour__"]')
    expect(labourOption.exists()).toBe(true)
    expect(wrapper.find('[data-value="s1"]').exists()).toBe(false)
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

    const stockOption = wrapper.find('[data-value="s1"]')
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

  it('keeps sub-3-character queries local and does not render the full stock cache', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = [
      buildStockItem({ id: 's1', description: 'Steel sheet' }),
      buildStockItem({ id: 's2', description: 'Aluminium bar' }),
    ]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)

    const wrapper = mount(ItemSelect, {
      props: { modelValue: null, tabKind: 'estimate' },
    })
    await flushPromises()

    const input = wrapper.find('input')
    await input.setValue('st')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()
    expect(wrapper.find('[data-value="__labour__"]').exists()).toBe(true)
    expect(wrapper.find('[data-value="s1"]').exists()).toBe(false)
    expect(wrapper.find('[data-value="s2"]').exists()).toBe(false)

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

    const stockOption = wrapper.find('[data-value="s1"]')
    const signature = stockOption.find('[data-automation-id="ItemSelect-variant-signature"]')
    expect(signature.exists()).toBe(true)
    expect(signature.text()).toBe('316 · 1.5mm sheet')
    expect(stockOption.text()).not.toContain('unspecified')

    vi.useRealTimers()
  })
})
