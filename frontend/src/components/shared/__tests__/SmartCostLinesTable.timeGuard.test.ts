import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'

const { scheduleSaveMock, saveNowMock, toastErrorMock } = vi.hoisted(() => ({
  scheduleSaveMock: vi.fn(),
  saveNowMock: vi.fn(),
  toastErrorMock: vi.fn(),
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

// Company defaults NOT loaded: wage_rate is unset. Reading it via requiredNumber
// would throw, so the guard must abort the conversion and toast instead.
vi.mock('@/stores/companyDefaults', () => ({
  useCompanyDefaultsStore: () => ({
    companyDefaults: { materials_markup: 0.2 },
    isLoaded: false,
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
    getJobLabourRates: vi.fn().mockResolvedValue([
      {
        labour_subtype: 'sub-workshop',
        labour_subtype_name: 'Workshop',
        charge_out_rate: 100,
        is_workshop: true,
      },
    ]),
  },
}))

vi.mock('@/services/costline.service', () => ({
  costlineService: {
    updateCostLine: vi.fn(),
  },
}))

// Capture the item column's 'onUpdate:kind' handler so the test can invoke the
// time conversion the way the picker would, without depending on the table's
// lazy-mount/active-row machinery.
const { kindHandlers } = vi.hoisted(() => ({
  kindHandlers: [] as Array<(kind: string) => void>,
}))

// Render the item column for row 0 so its ItemSelect (and the kind handler)
// mount. Force the row active by also rendering the cell with a selected index.
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
        const itemColumn = columns.find((column) => column.id === 'item')
        return h('div', itemColumn ? [itemColumn.cell({ row: { index: 0 } })] : [])
      }
    },
  }),
}))

// ItemSelect stub: in inactive mode the table renders a plain Button, so this
// stub only mounts when the row is active. Capture the kind handler the parent
// wires so the test can trigger the conversion regardless of render timing.
vi.mock('@/views/purchasing/ItemSelect.vue', () => ({
  default: defineComponent({
    name: 'ItemSelect',
    props: {
      modelValue: { type: [String, null], default: null },
      'onUpdate:kind': { type: Function, default: undefined },
    },
    emits: ['update:modelValue', 'update:open', 'update:kind', 'update:unit_cost'],
    setup(props) {
      const handler = props['onUpdate:kind'] as ((kind: string) => void) | undefined
      if (typeof handler === 'function') kindHandlers.push(handler)
      return () => h('div', { 'data-test': 'item-select-stub' })
    },
  }),
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: toastErrorMock,
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

const stubs = {
  Button: { template: '<button @click="$emit(\'click\', $event)"><slot /></button>' },
  Badge: { template: '<span><slot /></span>' },
  Input: { template: '<input />' },
  Textarea: { template: '<textarea />' },
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

describe('SmartCostLinesTable time-conversion guard before company defaults load', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    kindHandlers.length = 0
  })

  it('aborts converting a line to time when wage_rate is unset, toasting instead of throwing', async () => {
    const line = makeLine()
    const wrapper = mount(SmartCostLinesTable, {
      props: { lines: [line], tabKind: 'estimate', persistNewLine: vi.fn() },
      global: { stubs },
    })

    // Select the row to mount the active ItemSelect (lazy-mount button first).
    // The item cell's button lives inside the item container; the page also has
    // a Shortcuts button, so scope the query to the item cell.
    await wrapper.get('[data-automation-id="SmartCostLinesTable-item-0"] button').trigger('click')
    await wrapper.vm.$nextTick()

    // Pick the labour/time kind: triggers updateLineKind(line, 'time').
    const kindHandler = kindHandlers.at(-1)
    expect(kindHandler).toBeTypeOf('function')
    kindHandler!('time')
    await wrapper.vm.$nextTick()

    // The conversion is aborted: kind unchanged, no unit_cost rewrite, no save.
    expect(String(line.kind)).toBe('material')
    expect(line.unit_cost).toBe(10)
    expect(scheduleSaveMock).not.toHaveBeenCalled()
    // The user is told defaults are still loading.
    expect(toastErrorMock).toHaveBeenCalledWith(
      'Company defaults are still loading. Please try again.',
    )
  })
})
