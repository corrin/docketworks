import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const onKeydownSpy = vi.fn()

vi.mock('../../../composables/useGridKeyboardNav', () => ({
  useGridKeyboardNav: vi.fn(() => ({ onKeydown: onKeydownSpy })),
}))

vi.mock('../../../services/costline.service', () => ({
  costlineService: {
    updateCostLine: vi.fn().mockResolvedValue({}),
    createCostLine: vi.fn().mockResolvedValue({ id: 'new-1' }),
    deleteCostLine: vi.fn().mockResolvedValue(undefined),
  },
}))

vi.mock('../../../utils/error-handler', () => ({ logError: vi.fn() }))
vi.mock('../../../utils/debug', () => ({ debugLog: vi.fn() }))

import SmartTimesheetTable from '../SmartTimesheetTable.vue'
import TimesheetJobPicker from '../TimesheetJobPicker.vue'
import HoursCell from '../HoursCell.vue'
import { costlineService } from '../../../services/costline.service'

const sampleJob = {
  id: 'j1',
  job_number: 100,
  name: 'Test Job',
  client_name: 'Test Client',
  charge_out_rate: 120,
  status: 'in_progress',
  shop_job: false,
  default_xero_pay_item_id: null,
  default_xero_pay_item_name: null,
}

function buildSavedEntry(over: Record<string, unknown> = {}) {
  const now = new Date().toISOString()
  return {
    id: 'cl-1',
    kind: 'time',
    desc: 'Saved row',
    quantity: 1,
    unit_cost: 30,
    unit_rev: 100,
    ext_refs: {},
    meta: { staff_id: 's1', date: '2026-05-01', is_billable: true, wage_rate_multiplier: 1.0 },
    created_at: now,
    updated_at: now,
    accounting_date: '2026-05-01',
    xero_time_id: null,
    xero_expense_id: null,
    xero_last_modified: null,
    xero_last_synced: null,
    approved: false,
    xero_pay_item: null,
    total_cost: 30,
    total_rev: 100,
    job_id: 'j1',
    job_number: 100,
    job_name: 'Test Job',
    client_name: 'Test Client',
    charge_out_rate: 100,
    wage_rate: 30,
    xero_pay_item_name: '',
    ...over,
  }
}

const baseProps = {
  entries: [],
  staffId: 's1',
  staffWageRate: 30,
  defaultChargeOutRate: 100,
  accountingDate: '2026-05-01',
  jobs: [sampleJob],
  payItemsByMultiplier: {},
}

describe('SmartTimesheetTable description keydown (C2 — defensive contract)', () => {
  beforeEach(() => {
    onKeydownSpy.mockReset()
  })

  it('plain Enter on the description Textarea blurs the field instead of inserting a newline', async () => {
    const wrapper = mount(SmartTimesheetTable, { props: baseProps })
    await flushPromises()

    const textarea = wrapper.find('[data-automation-id="SmartTimesheetTable-description-0"]')
    const blurSpy = vi.spyOn(textarea.element as HTMLElement, 'blur')

    const ev = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    textarea.element.dispatchEvent(ev)

    expect(ev.defaultPrevented).toBe(true)
    expect(blurSpy).toHaveBeenCalled()
    // Plain Enter still bubbles, but the grid wires no commitEdit/startEdit
    // callback, so it's a harmless no-op at the grid level. We only need to
    // guarantee the cell-level blur — the bubble path is incidental.
  })

  it('Ctrl/Cmd+Enter from the description Textarea is swallowed by the cell, not surfaced as a grid shortcut', async () => {
    // The grid wires Ctrl/Cmd+Enter to addLine, which mutates a private
    // selectedRowIndex with no visible effect (see Trello #308). Letting it
    // bubble exposes other grid shortcuts (Ctrl+Backspace = deleteSelected)
    // to a user mid-edit, which is destructive.
    const wrapper = mount(SmartTimesheetTable, { props: baseProps })
    await flushPromises()

    const textarea = wrapper.find('[data-automation-id="SmartTimesheetTable-description-0"]')
    const ev = new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true })
    textarea.element.dispatchEvent(ev)

    expect(onKeydownSpy).not.toHaveBeenCalled()
  })

  it('Ctrl+Backspace from the description Textarea does NOT bubble to deleteSelected', async () => {
    // Regression guard: a user mid-word reaching for "delete previous word"
    // (Ctrl+Backspace) must not delete the row.
    const wrapper = mount(SmartTimesheetTable, { props: baseProps })
    await flushPromises()

    const textarea = wrapper.find('[data-automation-id="SmartTimesheetTable-description-0"]')
    const ev = new KeyboardEvent('keydown', {
      key: 'Backspace',
      ctrlKey: true,
      bubbles: true,
    })
    textarea.element.dispatchEvent(ev)

    expect(onKeydownSpy).not.toHaveBeenCalled()
  })
})

describe('SmartTimesheetTable job picker is disabled on saved rows (C4)', () => {
  it('saved row picker is disabled; phantom row picker is enabled', async () => {
    const saved = buildSavedEntry()
    const wrapper = mount(SmartTimesheetTable, {
      props: { ...baseProps, entries: [saved] },
    })
    await flushPromises()

    const pickers = wrapper.findAllComponents(TimesheetJobPicker)
    expect(pickers).toHaveLength(2)
    // Saved row (index 0): cost-line→job linkage isn't a writable field on the
    // PATCH endpoint, so the picker must be disabled — otherwise the UI would
    // silently drift from the server.
    expect(pickers[0].props('disabled')).toBe(true)
    // Phantom row (index 1): user must be able to pick a job for the new entry.
    expect(pickers[1].props('disabled')).toBe(false)
  })
})

describe('SmartTimesheetTable description save on a saved row', () => {
  it('typing a new description on a saved row and pressing Enter persists the new desc', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(costlineService.updateCostLine).mockClear()
    vi.mocked(costlineService.updateCostLine).mockResolvedValue({})

    const saved = buildSavedEntry({ desc: 'old description' })
    const wrapper = mount(SmartTimesheetTable, {
      props: { ...baseProps, entries: [saved] },
    })
    await flushPromises()

    // Click into the description on the saved row (index 0).
    const textarea = wrapper.find<HTMLTextAreaElement>(
      '[data-automation-id="SmartTimesheetTable-description-0"]',
    )
    expect(textarea.exists()).toBe(true)

    // Focus, then change ONLY the description. setValue triggers v-model's
    // onUpdate:modelValue, which mirrors the live-typing path (entry.desc
    // gets pre-mutated each keystroke).
    textarea.element.focus()
    await textarea.setValue('new description')

    // Press Enter — handler must preventDefault and blur the field. The blur
    // event then triggers @blur → setDescription → commit → autosave.
    await textarea.trigger('keydown', { key: 'Enter' })

    // happy-dom doesn't always emit the blur event for programmatic .blur(),
    // so trigger it explicitly to mirror the real-browser flow.
    await textarea.trigger('blur')

    // Past the 600ms autosave debounce.
    await vi.advanceTimersByTimeAsync(700)
    await flushPromises()

    expect(costlineService.updateCostLine).toHaveBeenCalledTimes(1)
    const [id, patch] = vi.mocked(costlineService.updateCostLine).mock.calls[0]
    expect(id).toBe('cl-1')
    expect(patch).toEqual({ desc: 'new description' })

    vi.useRealTimers()
  })
})

describe('SmartTimesheetTable phantom row reflects current parent props after :key change (C1)', () => {
  it('parent re-keying on staff/date causes the next create-entry to carry fresh wage and date', async () => {
    type Emitted = { unit_cost: number; accounting_date: string }
    const events: Emitted[] = []

    const Harness = defineComponent({
      components: { SmartTimesheetTable },
      props: {
        staffId: { type: String, required: true },
        wage: { type: Number, required: true },
        date: { type: String, required: true },
      },
      setup() {
        const onCreate = (e: { unit_cost: number; accounting_date: string }) => {
          events.push({ unit_cost: e.unit_cost, accounting_date: e.accounting_date })
        }
        return { onCreate, jobs: [sampleJob] }
      },
      template: `
        <SmartTimesheetTable
          :key="staffId + '|' + date"
          :staff-id="staffId"
          :staff-wage-rate="wage"
          :accounting-date="date"
          :default-charge-out-rate="100"
          :entries="[]"
          :jobs="jobs"
          :pay-items-by-multiplier="{}"
          @create-entry="onCreate"
        />
      `,
    })

    const wrapper = mount(Harness, {
      props: { staffId: 's1', wage: 30, date: '2026-05-01' },
    })
    await flushPromises()

    // Drive the create flow on the phantom: pick a job, then commit hours.
    wrapper.findComponent(TimesheetJobPicker).vm.$emit('select', sampleJob)
    await flushPromises()
    wrapper.findComponent(HoursCell).vm.$emit('commit', '1')
    await flushPromises()

    expect(events).toHaveLength(1)
    expect(events[0].unit_cost).toBe(30)
    expect(events[0].accounting_date).toBe('2026-05-01')

    // Switch staff and date. The :key change must remount SmartTimesheetTable
    // so the phantom row rebuilds against the new props — without this, the
    // next POST would carry the previous staff's wage rate and date.
    await wrapper.setProps({ staffId: 's2', wage: 50, date: '2026-05-08' })
    await flushPromises()

    wrapper.findComponent(TimesheetJobPicker).vm.$emit('select', sampleJob)
    await flushPromises()
    wrapper.findComponent(HoursCell).vm.$emit('commit', '1')
    await flushPromises()

    expect(events).toHaveLength(2)
    expect(events[1].unit_cost).toBe(50)
    expect(events[1].accounting_date).toBe('2026-05-08')
  })
})
