/**
 * Draft lifecycle coverage for the cost-entry grid (KAN-296).
 *
 * Business risk: a row the operator has filled in must reach the server exactly
 * once. The failure mode these guard against is a row that looks entered, is
 * present on no server record, and consumed no stock.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'

// Shared across mounts so tests can inspect what the table asked to persist.
const { autosave } = vi.hoisted(() => ({
  autosave: {
    scheduleSave: vi.fn(),
    saveNow: vi.fn(),
    onBlurSave: vi.fn(),
    cancel: vi.fn(),
    clearStatus: vi.fn(),
  },
}))

vi.mock('@/composables/useCostLineAutosave', () => ({
  useCostLineAutosave: () => autosave,
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
    items: [
      {
        id: 'stock-1',
        item_code: 'SS-304',
        description: 'Stainless sheet 304',
        unit_cost: 25,
        unit_revenue: null,
        quantity: 100,
      },
    ],
    loading: false,
    fetchStock: vi.fn(),
  }),
}))

const WORKSHOP_SUBTYPE_ID = '22222222-2222-4222-8222-222222222222'

vi.mock('@/services/job.service', () => ({
  jobService: {
    getJobLabourRates: vi.fn().mockResolvedValue([
      {
        id: '11111111-1111-4111-8111-111111111111',
        labour_subtype: '22222222-2222-4222-8222-222222222222',
        labour_subtype_name: 'Workshop',
        is_workshop: true,
        charge_out_rate: 65,
      },
    ]),
  },
}))

vi.mock('@/services/costline.service', () => ({
  costlineService: { updateCostLine: vi.fn() },
}))

vi.mock('@/composables/useDataFreshness', () => ({
  dataFreshness: { checkFreshness: vi.fn().mockResolvedValue(undefined) },
}))

// Stub the stock picker with a button that emits the selection the real
// ItemSelect emits when the user picks a stock item.
vi.mock('@/views/purchasing/ItemSelect.vue', () => ({
  default: defineComponent({
    name: 'ItemSelect',
    props: { modelValue: { type: String, default: null } },
    emits: ['update:modelValue'],
    setup(_props, { emit }) {
      return () =>
        h('button', {
          'data-testid': 'pick-stock',
          onClick: () => emit('update:modelValue', 'stock-1'),
        })
    },
  }),
}))

const { capturedRows } = vi.hoisted(() => ({ capturedRows: [] as unknown[] }))

vi.mock('@/components/DataTable.vue', () => ({
  default: defineComponent({
    name: 'DataTable',
    props: { columns: { type: Array, required: true }, data: { type: Array, required: true } },
    setup(props) {
      return () => {
        capturedRows.length = 0
        capturedRows.push(...(props.data as unknown[]))
        const columns = props.columns as Array<{
          id: string
          cell: (ctx: { row: { index: number } }) => unknown
        }>
        const tested = columns.filter((c) =>
          ['desc', 'item', 'unit_cost', 'unit_rev'].includes(c.id),
        )
        return h(
          'div',
          tested.map((c) => c.cell({ row: { index: 0 } })),
        )
      }
    },
  }),
}))

vi.mock('vue-sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }))

import SmartCostLinesTable from '../SmartCostLinesTable.vue'
import { useCostLineDrafts, type CostLineDraft } from '@/composables/useCostLineDrafts'

type CostLine = z.infer<typeof schemas.CostLine>

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

/** Mounts the table over a real draft session, as the job tabs do. */
function mountWithRealDrafts(options: {
  tabKind: 'estimate' | 'quote' | 'actual'
  createLine?: (draft: CostLineDraft) => Promise<CostLine>
  consumeStockFn?: (payload: unknown) => Promise<void>
  lines?: CostLine[]
}) {
  const costLines = ref<CostLine[]>([])
  const createLine =
    options.createLine ?? (async (draft: CostLineDraft) => ({ ...draft, id: 'server-1' }))
  const createLineSpy = vi.fn(createLine)
  const session = useCostLineDrafts({ costLines, createLine: createLineSpy })
  const deleteDraftSpy = vi.fn(session.deleteDraft)

  const Host = defineComponent({
    setup() {
      return () =>
        h(SmartCostLinesTable, {
          lines: options.lines ?? [],
          tabKind: options.tabKind,
          showItemColumn: true,
          jobId: 'job-1',
          consumeStockFn: options.consumeStockFn,
          draftSession: { ...session, deleteDraft: deleteDraftSpy },
        })
    },
  })
  const wrapper = mount(Host, { attachTo: document.body, global: { stubs } })
  // createLineSpy captures the payload actually sent to the server. Asserting on
  // the object handed to persistDraft would be meaningless: persistDraft re-reads
  // the live draft internally.
  return { wrapper, session, createLineSpy, deleteDraftSpy, costLines }
}

/** Description-first entry: type a description, then activate the row. */
async function typeDescriptionThenActivateRow(wrapper: ReturnType<typeof mount>) {
  await wrapper.get('textarea').setValue('Custom bracket')
  // Select row 0 so the Item column leaves its lazy-mounted read-only state.
  await wrapper.get('[tabindex="0"]').trigger('keydown', { key: 'ArrowDown' })
  await flushPromises()
}

describe('description-first stock selection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('persists an estimate row exactly once, at selection time', async () => {
    const { wrapper, createLineSpy } = mountWithRealDrafts({ tabKind: 'estimate' })
    await typeDescriptionThenActivateRow(wrapper)

    await wrapper.get('[data-testid="pick-stock"]').trigger('click')
    await flushPromises()

    // The row saves on selection -- it must not depend on the operator blurring
    // out of the row to be rescued.
    expect(createLineSpy).toHaveBeenCalledOnce()
    const posted = createLineSpy.mock.calls[0][0]
    expect({ desc: posted.desc, unit_cost: posted.unit_cost, unit_rev: posted.unit_rev }).toEqual({
      desc: 'Stainless sheet 304',
      unit_cost: 25,
      unit_rev: 30,
    })

    // Leaving the row afterwards must not create a second server row.
    await wrapper.get('textarea').trigger('blur', { relatedTarget: null })
    await flushPromises()
    expect(createLineSpy).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('consumes stock exactly once on the actual tab and strands no draft', async () => {
    const consumeStockFn = vi.fn().mockResolvedValue(undefined)
    const { wrapper, session, createLineSpy } = mountWithRealDrafts({
      tabKind: 'actual',
      consumeStockFn,
    })
    await typeDescriptionThenActivateRow(wrapper)

    await wrapper.get('[data-testid="pick-stock"]').trigger('click')
    await flushPromises()

    // Actual material lines are created by stock consumption, never by a plain
    // create -- so the consume must fire off the selected kind.
    expect(consumeStockFn).toHaveBeenCalledOnce()
    expect(consumeStockFn.mock.calls[0][0]).toMatchObject({
      stockId: 'stock-1',
      quantity: 1,
      unitCost: 25,
      unitRev: 30,
    })
    expect(createLineSpy).not.toHaveBeenCalled()

    // The consumed row now exists on the server; the local draft must be gone or
    // the operator sees the row twice.
    expect(session.drafts.value).toEqual([])

    // Leaving the row must not consume a second time.
    await wrapper.get('textarea').trigger('blur', { relatedTarget: null })
    await flushPromises()
    expect(consumeStockFn).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('keeps the draft when stock consumption fails, so the work is not lost', async () => {
    const consumeStockFn = vi.fn().mockRejectedValue(new Error('consume failed'))
    const { wrapper, session } = mountWithRealDrafts({ tabKind: 'actual', consumeStockFn })
    await typeDescriptionThenActivateRow(wrapper)

    await wrapper.get('[data-testid="pick-stock"]').trigger('click')
    await flushPromises()

    expect(consumeStockFn).toHaveBeenCalledOnce()
    expect(session.drafts.value).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('converting a labour row to a stock item', () => {
  beforeEach(() => vi.clearAllMocks())

  it('prices the converted row off the part, not the staff wage', async () => {
    // Business risk: the row keeps the wage in unit_cost until the stock cost
    // replaces it. Deriving revenue before that swap charges the customer
    // markup on a labour rate that no longer applies to the line, and the
    // number looks plausible on screen either way.
    const timeLine: CostLine = {
      id: 'server-time-1',
      kind: 'time',
      desc: 'Workshop labour',
      quantity: 2,
      unit_cost: 40, // company wage rate
      unit_rev: 65,
      total_cost: 80,
      total_rev: 130,
      accounting_date: '2026-07-27',
      ext_refs: {},
      meta: {},
      labour_subtype: WORKSHOP_SUBTYPE_ID,
    }
    const { wrapper } = mountWithRealDrafts({ tabKind: 'estimate', lines: [timeLine] })

    // Select the row so the Item cell leaves its lazy-mounted read-only state.
    await wrapper.get('[tabindex="0"]').trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()

    await wrapper.get('[data-testid="pick-stock"]').trigger('click')
    await flushPromises()

    expect(autosave.saveNow).toHaveBeenCalled()
    // saveNow merges into any pending patch and cancels the debounce, so this
    // payload is what actually reaches the server.
    const [savedLine, patch] = autosave.saveNow.mock.calls.at(-1) as [
      CostLine,
      Record<string, unknown>,
    ]
    expect(savedLine.id).toBe('server-time-1')
    expect(patch).toMatchObject({
      desc: 'Stainless sheet 304',
      unit_cost: 25,
      // 25 * 1.2. Deriving from the wage still in unit_cost would give 48.
      unit_rev: 30,
      ext_refs: { stock_id: 'stock-1' },
    })

    const converted = capturedRows[0] as CostLine
    expect(converted.kind).toBe('material')
    expect(converted.labour_subtype).toBeNull()
    wrapper.unmount()
  })
})

describe('replacing the item on a saved row', () => {
  beforeEach(() => vi.clearAllMocks())

  it('preserves unrelated ext_refs', async () => {
    // Business risk: the backend replaces ext_refs wholesale, so a patch sending
    // only stock_id drops delivery-receipt and PO references. The local row
    // merges, so the two diverge silently until the next reload.
    const materialLine: CostLine = {
      id: 'server-material-1',
      kind: 'material',
      desc: 'Superseded part',
      quantity: 1,
      unit_cost: 10,
      unit_rev: 12,
      total_cost: 10,
      total_rev: 12,
      accounting_date: '2026-07-27',
      ext_refs: { po_number: 'PO-1234', stock_id: 'stock-old' },
      meta: {},
      labour_subtype: null,
    }
    const { wrapper } = mountWithRealDrafts({ tabKind: 'estimate', lines: [materialLine] })

    await wrapper.get('[tabindex="0"]').trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()

    await wrapper.get('[data-testid="pick-stock"]').trigger('click')
    await flushPromises()

    expect(autosave.saveNow).toHaveBeenCalled()
    const [, patch] = autosave.saveNow.mock.calls.at(-1) as [CostLine, Record<string, unknown>]
    expect(patch.ext_refs).toEqual({ po_number: 'PO-1234', stock_id: 'stock-1' })
    wrapper.unmount()
  })
})

describe('manual unit revenue override', () => {
  beforeEach(() => vi.clearAllMocks())

  it('survives a later unit cost change', async () => {
    const { wrapper } = mountWithRealDrafts({ tabKind: 'estimate' })
    await wrapper.get('textarea').setValue('Custom bracket')
    await wrapper.get('[data-automation-id="SmartCostLinesTable-unit-cost-0"]').setValue('10')
    await wrapper.get('[data-automation-id="SmartCostLinesTable-unit-rev-0"]').setValue('77')
    await wrapper.get('[data-automation-id="SmartCostLinesTable-unit-cost-0"]').setValue('20')
    await flushPromises()

    // If the override marker were lost, unit_rev would be recalculated to 24.
    expect((capturedRows[0] as CostLineDraft).unit_rev).toBe(77)
    wrapper.unmount()
  })

  it('is replaced by the stock unit revenue when an item is picked', async () => {
    const { wrapper, createLineSpy } = mountWithRealDrafts({ tabKind: 'estimate' })
    await wrapper.get('textarea').setValue('Custom bracket')
    await wrapper.get('[data-automation-id="SmartCostLinesTable-unit-cost-0"]').setValue('10')
    await wrapper.get('[data-automation-id="SmartCostLinesTable-unit-rev-0"]').setValue('77')
    await wrapper.get('[tabindex="0"]').trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()

    await wrapper.get('[data-testid="pick-stock"]').trigger('click')
    await flushPromises()

    expect(createLineSpy).toHaveBeenCalledOnce()
    const posted = createLineSpy.mock.calls[0][0]
    expect({ desc: posted.desc, unit_cost: posted.unit_cost, unit_rev: posted.unit_rev }).toEqual({
      desc: 'Stainless sheet 304',
      unit_cost: 25,
      unit_rev: 30,
    })
    wrapper.unmount()
  })
})

describe('keyboard delete of an owned draft', () => {
  beforeEach(() => vi.clearAllMocks())

  it('removes an unlocked draft, matching the Delete button', async () => {
    const { wrapper, deleteDraftSpy, session } = mountWithRealDrafts({ tabKind: 'estimate' })
    await wrapper.get('textarea').setValue('Custom bracket')
    await flushPromises()
    expect(session.drafts.value).toHaveLength(1)

    const container = wrapper.get('[tabindex="0"]')
    await container.trigger('keydown', { key: 'ArrowDown' }) // select row 0
    await container.trigger('keydown', { key: 'Backspace', ctrlKey: true })
    await flushPromises()

    expect(deleteDraftSpy).toHaveBeenCalledOnce()
    expect(session.drafts.value).toEqual([])
    wrapper.unmount()
  })

  it('protects a draft that is mid-save', async () => {
    // Never resolves: the draft stays in the 'saving' state for the whole test.
    const { wrapper, session } = mountWithRealDrafts({
      tabKind: 'estimate',
      createLine: () => new Promise<CostLine>(() => {}),
    })
    await wrapper.get('textarea').setValue('Custom bracket')
    await wrapper.get('[data-automation-id="SmartCostLinesTable-unit-cost-0"]').setValue('10')
    await flushPromises()
    // Blur out of the row to start the save.
    await wrapper.get('textarea').trigger('blur', { relatedTarget: null })
    await flushPromises()
    expect(session.drafts.value[0].__status).toBe('saving')

    const container = wrapper.get('[tabindex="0"]')
    await container.trigger('keydown', { key: 'ArrowDown' })
    await container.trigger('keydown', { key: 'Backspace', ctrlKey: true })
    await flushPromises()

    // A POST is in flight for this row; discarding it locally would lose track of
    // a line the server is about to create.
    expect(session.drafts.value).toHaveLength(1)
    wrapper.unmount()
  })
})
