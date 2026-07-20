import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'

const { saveNowMock } = vi.hoisted(() => ({
  saveNowMock: vi.fn(),
}))

vi.mock('@/composables/useCostLineAutosave', () => ({
  useCostLineAutosave: () => ({
    scheduleSave: vi.fn(),
    saveNow: saveNowMock,
    onBlurSave: vi.fn(),
    cancel: vi.fn(),
    clearStatus: vi.fn(),
  }),
}))

vi.mock('@/stores/companyDefaults', () => ({
  useCompanyDefaultsStore: () => ({
    companyDefaults: { wage_rate: 40, materials_markup: 0.2 },
    isLoaded: true,
    isLoading: false,
    loadCompanyDefaults: vi.fn(),
  }),
}))

vi.mock('@/stores/stockStore', () => ({
  useStockStore: () => ({
    items: [],
    loading: true,
    fetchStock: vi.fn(),
  }),
}))

vi.mock('@/services/job.service', () => ({
  jobService: {
    getJobLabourRates: vi.fn().mockResolvedValue([]),
  },
}))

vi.mock('@/services/costline.service', () => ({
  costlineService: {
    updateCostLine: vi.fn(),
  },
}))

vi.mock('@/components/DataTable.vue', () => ({
  default: defineComponent({
    name: 'DataTable',
    props: {
      columns: { type: Array, required: true },
      data: { type: Array, required: true },
    },
    setup(props) {
      return () => {
        const columns = props.columns as Array<{
          id: string
          cell: (ctx: { row: { index: number } }) => unknown
        }>
        const renderedColumns = ['quantity', 'unit_cost', 'unit_rev']
          .map((id) => columns.find((column) => column.id === id))
          .filter((column): column is NonNullable<typeof column> => column !== undefined)
        return h(
          'div',
          renderedColumns.map((column) => column.cell({ row: { index: 0 } })),
        )
      }
    },
  }),
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import SmartCostLinesTable from '../SmartCostLinesTable.vue'

type CostLine = z.infer<typeof schemas.CostLine> & {
  created_at?: string
  updated_at?: string
}

function makeLine(): CostLine {
  return {
    id: 'line-1',
    kind: 'material',
    desc: 'Material',
    quantity: 1,
    unit_cost: 10,
    unit_rev: 12,
    ext_refs: {},
    meta: {},
    total_cost: 10,
    total_rev: 12,
    accounting_date: '2026-06-19',
    labour_subtype: null,
  } as CostLine
}

describe('SmartCostLinesTable draft inputs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('allows clearing unit cost as incomplete draft state without saving', async () => {
    const line = makeLine()
    const wrapper = mount(SmartCostLinesTable, {
      props: {
        lines: [line],
        tabKind: 'estimate',
        draftSession: {
          drafts: ref([]),
          addDraft: vi.fn(),
          updateDraft: vi.fn(),
          persistDraft: vi.fn(),
          deleteDraft: vi.fn(),
        },
      },
      global: {
        stubs: {
          Button: { template: '<button><slot /></button>' },
          Badge: { template: '<span><slot /></span>' },
          Dialog: { template: '<div><slot /></div>' },
          DialogContent: { template: '<div><slot /></div>' },
          DialogHeader: { template: '<div><slot /></div>' },
          DialogTitle: { template: '<div><slot /></div>' },
          DialogDescription: { template: '<div><slot /></div>' },
          DialogFooter: { template: '<div><slot /></div>' },
          HelpCircle: { template: '<span />' },
          Trash2: { template: '<span />' },
          AlertTriangle: { template: '<span />' },
          Check: { template: '<span />' },
        },
      },
    })

    await wrapper.get('[data-automation-id="SmartCostLinesTable-unit-cost-0"]').setValue('')

    expect(line.unit_cost).toBeNull()
    expect(saveNowMock).not.toHaveBeenCalled()
  })

  it('marks job cost-line numeric fields as numeric grid inputs', () => {
    const wrapper = mount(SmartCostLinesTable, {
      props: {
        lines: [makeLine()],
        tabKind: 'estimate',
        draftSession: {
          drafts: ref([]),
          addDraft: vi.fn(),
          updateDraft: vi.fn(),
          persistDraft: vi.fn(),
          deleteDraft: vi.fn(),
        },
      },
      global: {
        stubs: {
          Button: { template: '<button><slot /></button>' },
          Badge: { template: '<span><slot /></span>' },
          Dialog: { template: '<div><slot /></div>' },
          DialogContent: { template: '<div><slot /></div>' },
          DialogHeader: { template: '<div><slot /></div>' },
          DialogTitle: { template: '<div><slot /></div>' },
          DialogDescription: { template: '<div><slot /></div>' },
          DialogFooter: { template: '<div><slot /></div>' },
          HelpCircle: { template: '<span />' },
          Trash2: { template: '<span />' },
          AlertTriangle: { template: '<span />' },
          Check: { template: '<span />' },
        },
      },
    })

    const expectedFields = [
      ['SmartCostLinesTable-quantity-0', 'quantity'],
      ['SmartCostLinesTable-unit-cost-0', 'unit_cost'],
      ['SmartCostLinesTable-unit-rev-0', 'unit_rev'],
    ] as const

    for (const [automationId, gridColumn] of expectedFields) {
      const input = wrapper.get<HTMLInputElement>(`[data-automation-id="${automationId}"]`)
      expect(input.attributes('data-grid-nav-cell')).toBe('true')
      expect(input.attributes('data-grid-row')).toBe('0')
      expect(input.attributes('data-grid-col')).toBe(gridColumn)
      expect(input.attributes('type')).toBe('number')
      expect(input.attributes('inputmode')).toBe('decimal')
      expect(input.classes()).toContain('numeric-input')
    }
  })
})
