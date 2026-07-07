import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'

const { scheduleSaveMock, saveNowMock } = vi.hoisted(() => ({
  scheduleSaveMock: vi.fn(),
  saveNowMock: vi.fn(),
}))

vi.mock('@/composables/useCostLineAutosave', () => ({
  useCostLineAutosave: () => ({
    scheduleSave: scheduleSaveMock,
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

// Capture the rows the table passes to DataTable so tests can inspect the
// phantom (empty) row, and render only the desc column for row 0 — the cell
// whose typing handler infers kind 'adjust'.
const { capturedRows } = vi.hoisted(() => ({
  capturedRows: [] as unknown[],
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
        capturedRows.length = 0
        capturedRows.push(...(props.data as unknown[]))
        const columns = props.columns as Array<{
          id: string
          cell: (ctx: { row: { index: number } }) => unknown
        }>
        const descColumn = columns.find((column) => column.id === 'desc')
        return h('div', descColumn ? [descColumn.cell({ row: { index: 0 } })] : [])
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

const stubs = {
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
}

function mountTable(lines: CostLine[], onError: (err: unknown) => void) {
  return mount(SmartCostLinesTable, {
    props: { lines, tabKind: 'estimate' },
    global: {
      config: { errorHandler: onError },
      stubs,
    },
  })
}

describe('SmartCostLinesTable kind inference from description typing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('infers adjust on the phantom row (no unit_cost yet) without throwing and leaves unit_rev unset', async () => {
    const errors: unknown[] = []
    const wrapper = mountTable([], (err) => errors.push(err))

    // With no props.lines, row 0 is the phantom row: unit_cost not yet entered.
    const phantom = capturedRows[0] as CostLine
    expect(phantom.unit_cost).toBeUndefined()

    await wrapper.get('textarea').setValue('Site adjustment')

    expect(errors).toEqual([])
    expect(String(phantom.kind)).toBe('adjust')
    // unit_rev is derived later, when the user enters unit_cost.
    expect(phantom.unit_rev).toBeUndefined()
    expect(scheduleSaveMock).not.toHaveBeenCalled()
  })

  it('still derives unit_rev with markup when the converted line has a unit_cost', async () => {
    const line = {
      id: 'line-1',
      kind: 'material',
      desc: '',
      quantity: 1,
      unit_cost: 10,
      unit_rev: 5,
      ext_refs: {},
      meta: {},
      total_cost: 10,
      total_rev: 5,
      accounting_date: '2026-06-19',
      labour_subtype: null,
    } as CostLine
    const errors: unknown[] = []
    const wrapper = mountTable([line], (err) => errors.push(err))

    await wrapper.get('textarea').setValue('Adjustment')

    expect(errors).toEqual([])
    expect(String(line.kind)).toBe('adjust')
    // unit_cost 10 * (1 + materials_markup 0.2)
    expect(line.unit_rev).toBe(12)
  })
})
