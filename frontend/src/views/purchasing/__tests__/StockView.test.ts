import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

vi.mock('@/api/client', () => ({
  api: {
    purchasing_stock_search_retrieve: vi.fn(),
  },
}))

import { api } from '@/api/client'
const purchasing_stock_search_retrieve = api.purchasing_stock_search_retrieve as ReturnType<
  typeof vi.fn
>

vi.mock('@/services/job.service', () => ({
  jobService: {
    getAllJobs: vi.fn().mockResolvedValue({ active_jobs: [], archived_jobs: [] }),
  },
}))

vi.mock('@/components/AppLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))

vi.mock('@/utils/debug', () => ({ debugLog: vi.fn() }))

vi.mock('@/utils/string-formatting', () => ({
  formatCurrency: (n: number | null | undefined) => `$${(n ?? 0).toFixed(2)}`,
}))

import StockView from '@/pages/purchasing/stock.vue'
import { useStockStore } from '@/stores/stockStore'

function buildStockItem(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: over.id ?? 'stock-1',
    job_id: null,
    item_code: over.item_code ?? 'ABC',
    description: over.description ?? 'Stainless 5mm sheet',
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

describe('StockView server-side search', () => {
  it('renders Metal, Alloy, Spec, and Used columns from store items', async () => {
    const store = useStockStore()
    store.items = [
      buildStockItem({
        id: 's1',
        description: 'Stainless 5mm sheet',
        metal_type: 'stainless steel',
        alloy: '304',
        specifics: '5mm sheet',
        times_used: 7,
      }),
    ]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)

    const wrapper = mount(StockView)
    await flushPromises()

    const headers = wrapper.findAll('th').map((h) => h.text())
    expect(headers).toContain('Metal')
    expect(headers).toContain('Alloy')
    expect(headers).toContain('Spec')
    expect(headers).toContain('Used')

    const firstRowCells = wrapper.find('tbody tr').findAll('td')
    expect(firstRowCells[2].text()).toBe('stainless steel')
    expect(firstRowCells[3].text()).toBe('304')
    expect(firstRowCells[4].text()).toBe('5mm sheet')
    expect(firstRowCells[5].text()).toBe('7')
  })

  it('debounces input and calls the search API once after typing settles', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [buildStockItem({ id: 'r1', description: 'Stainless 5mm sheet', alloy: '304' })],
      count: 1,
      page: 1,
      page_size: 25,
      total_pages: 1,
    })

    const wrapper = mount(StockView)
    await flushPromises()

    const input = wrapper.find('input[placeholder="Search stock items..."]')
    await input.setValue('sta')
    await input.setValue('stai')
    await input.setValue('stainless')

    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(purchasing_stock_search_retrieve).toHaveBeenCalledTimes(1)
    expect(purchasing_stock_search_retrieve).toHaveBeenCalledWith({
      queries: { q: 'stainless', page: 1, page_size: 25 },
    })

    vi.useRealTimers()
  })

  it('does not fire an immediate search when typing resets page back to 1', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = []
    store.fetchStock = vi.fn().mockResolvedValue([])
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [buildStockItem({ id: 'r1', description: 'Stainless 5mm sheet', alloy: '304' })],
      count: 1,
      page: 1,
      page_size: 25,
      total_pages: 1,
    })

    const wrapper = mount(StockView)
    await flushPromises()

    wrapper.vm.page = 3
    await nextTick()

    const input = wrapper.find('input[placeholder="Search stock items..."]')
    await input.setValue('stainless')

    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(purchasing_stock_search_retrieve).toHaveBeenCalledTimes(1)
    expect(purchasing_stock_search_retrieve).toHaveBeenCalledWith({
      queries: { q: 'stainless', page: 1, page_size: 25 },
    })

    vi.useRealTimers()
  })

  it('falls back to the unfiltered store list when the search box is empty', async () => {
    const store = useStockStore()
    store.items = [
      buildStockItem({ id: 's1', description: 'Steel sheet', metal_type: 'steel' }),
      buildStockItem({ id: 's2', description: 'Aluminium bar', metal_type: 'aluminium' }),
    ]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)

    const wrapper = mount(StockView)
    await flushPromises()

    const rowDescriptions = wrapper.findAll('tbody tr').map((r) => r.findAll('td')[1]?.text())
    expect(rowDescriptions).toEqual(['Steel sheet', 'Aluminium bar'])
    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()
  })

  it('keeps sub-3-character queries local and does not call the search API', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = [
      buildStockItem({ id: 's1', description: 'Steel sheet', metal_type: 'steel' }),
      buildStockItem({ id: 's2', description: 'Aluminium bar', metal_type: 'aluminium' }),
    ]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)

    const wrapper = mount(StockView)
    await flushPromises()

    const input = wrapper.find('input[placeholder="Search stock items..."]')
    await input.setValue('st')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    const descriptions = wrapper.findAll('tbody tr').map((r) => r.findAll('td')[1]?.text())
    expect(descriptions).toEqual(['Steel sheet', 'Aluminium bar'])
    expect(purchasing_stock_search_retrieve).not.toHaveBeenCalled()

    vi.useRealTimers()
  })

  it('uses server results when query is active', async () => {
    vi.useFakeTimers()
    const store = useStockStore()
    store.items = [buildStockItem({ id: 'cached', description: 'Cached item' })]
    store.fetchStock = vi.fn().mockResolvedValue(store.items)
    purchasing_stock_search_retrieve.mockResolvedValue({
      results: [buildStockItem({ id: 'srv', description: 'Server-only result', alloy: '316' })],
      count: 1,
      page: 1,
      page_size: 25,
      total_pages: 1,
    })

    const wrapper = mount(StockView)
    await flushPromises()

    const input = wrapper.find('input[placeholder="Search stock items..."]')
    await input.setValue('316')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    await nextTick()

    const descriptions = wrapper.findAll('tbody tr').map((r) => r.findAll('td')[1]?.text())
    expect(descriptions).toEqual(['Server-only result'])

    vi.useRealTimers()
  })
})
