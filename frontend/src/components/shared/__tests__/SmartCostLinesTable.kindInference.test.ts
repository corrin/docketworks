import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
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
// phantom (empty) row, and render the fields used by these focused tests for row 0.
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
        const testedColumns = columns.filter((column) =>
          ['desc', 'unit_cost', 'unit_rev'].includes(column.id),
        )
        return h(
          'div',
          testedColumns.map((column) => column.cell({ row: { index: 0 } })),
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
import type { CostLineDraft } from '@/composables/useCostLineDrafts'

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
    props: {
      lines,
      tabKind: 'estimate',
      draftSession: {
        drafts: ref<CostLineDraft[]>([]),
        addDraft: (line) => ({
          ...line,
          __localId: 'test-draft',
          __status: 'idle',
          __error: null,
        }),
        updateDraft: (_localId, patch) => ({ ...lines[0], ...patch }) as CostLineDraft,
        persistDraft: vi.fn(),
        deleteDraft: vi.fn(),
      },
    },
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

  it('promotes a typed adjustment, leaves a new phantom, and creates only when ready', async () => {
    const draftLines = ref<CostLineDraft[]>([])
    const persistDraft = vi.fn(async (draft: CostLineDraft) => {
      draftLines.value = draftLines.value.filter(
        (candidate) => candidate.__localId !== draft.__localId,
      )
      return { ...draft, id: 'created-line' }
    })
    const Host = defineComponent({
      setup() {
        return () =>
          h(SmartCostLinesTable, {
            lines: [],
            tabKind: 'estimate',
            draftSession: {
              drafts: draftLines,
              addDraft: (line: CostLine) => {
                const draft = {
                  ...line,
                  __localId: '__localId' in line ? String(line.__localId) : 'test-draft',
                  __status: 'idle' as const,
                  __error: null,
                }
                draftLines.value = [...draftLines.value, draft]
                return draft
              },
              updateDraft: (localId: string, patch: Partial<CostLineDraft>) => {
                const current = draftLines.value.find((draft) => draft.__localId === localId)!
                const updated = { ...current, ...patch }
                draftLines.value = draftLines.value.map((draft) =>
                  draft.__localId === localId ? updated : draft,
                )
                return updated
              },
              persistDraft,
              deleteDraft: vi.fn(),
            },
          })
      },
    })
    const wrapper = mount(Host, { attachTo: document.body, global: { stubs } })

    await wrapper.get('textarea').setValue('Site adjustment')

    expect(capturedRows).toHaveLength(2)
    expect(capturedRows).toEqual([
      expect.objectContaining({ desc: 'Site adjustment', kind: 'adjust' }),
      expect.objectContaining({ desc: '' }),
    ])
    expect(persistDraft).not.toHaveBeenCalled()

    const unitCost = wrapper.get('[data-automation-id="SmartCostLinesTable-unit-cost-0"]')
    await unitCost.setValue('10')

    // Grid Tab navigation calls blur() before its deferred focus, producing a null
    // relatedTarget. That programmatic blur must not submit a ready draft while
    // the destination is another cell in the same row.
    const description = wrapper.get('textarea')
    description.element.focus()
    await description.trigger('keydown', { key: 'Tab' })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    expect(persistDraft).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(unitCost.element)

    await unitCost.trigger('blur', { relatedTarget: null })
    await flushPromises()

    expect(persistDraft).toHaveBeenCalledOnce()
    expect(persistDraft).toHaveBeenCalledWith(
      expect.objectContaining({ desc: 'Site adjustment', kind: 'adjust', unit_cost: 10 }),
    )
    expect(capturedRows).toHaveLength(1)
    wrapper.unmount()
  })

  it('keeps description focus and the stable row identity after the first character', async () => {
    const draftLines = ref<CostLineDraft[]>([])
    const Host = defineComponent({
      setup() {
        return () =>
          h(SmartCostLinesTable, {
            lines: [],
            tabKind: 'estimate',
            draftSession: {
              drafts: draftLines,
              addDraft: (line: CostLine) => {
                const draft = {
                  ...line,
                  __localId: String((line as CostLineDraft).__localId),
                  __status: 'idle' as const,
                  __error: null,
                }
                draftLines.value = [draft]
                return draft
              },
              updateDraft: (localId: string, patch: Partial<CostLineDraft>) => {
                const updated = { ...draftLines.value[0], ...patch, __localId: localId }
                draftLines.value = [updated]
                return updated
              },
              persistDraft: vi.fn(),
              deleteDraft: vi.fn(),
            },
          })
      },
    })
    const wrapper = mount(Host, { attachTo: document.body, global: { stubs } })
    const textarea = wrapper.get<HTMLTextAreaElement>('textarea')
    textarea.element.focus()
    const initialId = (capturedRows[0] as CostLineDraft).__localId

    await textarea.setValue('S')
    await wrapper.get('textarea').setValue('Site adjustment')

    expect(document.activeElement).toBe(wrapper.get('textarea').element)
    expect(wrapper.get<HTMLTextAreaElement>('textarea').element.value).toBe('Site adjustment')
    expect((capturedRows[0] as CostLineDraft).__localId).toBe(initialId)

    const unitCost = wrapper.get('[data-automation-id="SmartCostLinesTable-unit-cost-0"]')
    const unitRevenue = wrapper.get('[data-automation-id="SmartCostLinesTable-unit-rev-0"]')
    await unitCost.setValue('10')
    await unitRevenue.setValue('77')
    await wrapper.get('textarea').setValue('Updated adjustment')
    await unitCost.setValue('20')

    expect(
      wrapper.get<HTMLInputElement>('[data-automation-id="SmartCostLinesTable-unit-rev-0"]').element
        .value,
    ).toBe('77')
    wrapper.unmount()
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
