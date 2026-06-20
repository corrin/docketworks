import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'
import { getBillMultiplier } from '@/utils/timesheetCalc'

vi.mock('@/composables/useCostLineAutosave', () => ({
  useCostLineAutosave: () => ({
    scheduleSave: vi.fn(),
    clearStatus: vi.fn(),
  }),
}))

// Capture every onSelect handler so the test can drive setJob, and every onBill
// handler so it can drive setBill (the genuine user override path).
const { selectHandlers, billHandlers } = vi.hoisted(() => ({
  selectHandlers: [] as Array<(job: unknown) => void>,
  // Keyed by row automation-id (e.g. 'billRate-0') so the test targets the
  // saved entry's row, not the always-present phantom row.
  billHandlers: {} as Record<string, (rateType: string) => void>,
}))

vi.mock('@/components/timesheet/TimesheetJobPicker.vue', () => ({
  default: defineComponent({
    name: 'TimesheetJobPicker',
    props: { onSelect: { type: Function, default: undefined } },
    setup(props) {
      if (typeof props.onSelect === 'function') {
        selectHandlers.push(props.onSelect as (job: unknown) => void)
      }
      return () => h('div', { class: 'job-picker-stub' })
    },
  }),
}))

// Stub the UI Select so the test can capture the billRate column's
// onUpdate:modelValue handler — invoking it drives setBill exactly as a user
// choosing an Invoice multiplier in the dropdown would. The billRate Select is
// identified by its SelectTrigger's data-automation-id (it contains 'billRate'),
// since several Selects share the same option set.
function findBillRateAutoId(node: unknown): string | null {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findBillRateAutoId(child)
      if (found) return found
    }
    return null
  }
  if (!node || typeof node !== 'object') return null
  const vnode = node as { props?: Record<string, unknown> | null; children?: unknown }
  const autoId = vnode.props?.['data-automation-id']
  if (typeof autoId === 'string' && autoId.includes('billRate')) return autoId
  if (typeof vnode.children === 'object') return findBillRateAutoId(vnode.children)
  return null
}

vi.mock('@/components/ui/select', () => {
  const passthrough = (name: string) =>
    defineComponent({
      name,
      setup:
        (_p, { slots }) =>
        () =>
          h('div', slots.default?.() ?? []),
    })
  return {
    Select: defineComponent({
      name: 'SelectStub',
      props: {
        modelValue: { type: String, default: '' },
        'onUpdate:modelValue': { type: Function, default: undefined },
      },
      setup(props, { slots }) {
        const handler = props['onUpdate:modelValue'] as ((v: unknown) => void) | undefined
        const rendered = slots.default?.()
        const autoId = findBillRateAutoId(rendered)
        if (typeof handler === 'function' && autoId) {
          // e.g. 'SmartTimesheetTable-billRate-0' -> key 'billRate-0'
          const key = autoId.split('-').slice(-2).join('-')
          billHandlers[key] = handler as (rateType: string) => void
        }
        return () => h('div', rendered ?? [])
      },
    }),
    SelectContent: passthrough('SelectContent'),
    SelectItem: passthrough('SelectItem'),
    SelectTrigger: passthrough('SelectTrigger'),
    SelectValue: passthrough('SelectValue'),
  }
})

import SmartTimesheetTable from '../SmartTimesheetTable.vue'

type Job = z.infer<typeof schemas.ModernTimesheetJob>
type TimesheetCostLine = z.infer<typeof schemas.TimesheetCostLine>

function makeJob(overrides: Partial<Job>): Job {
  return {
    id: overrides.id ?? '11111111-1111-1111-1111-111111111111',
    job_number: overrides.job_number ?? 100,
    name: overrides.name ?? 'Test Job',
    client_name: overrides.client_name ?? 'Acme',
    status: overrides.status ?? 'in_progress',
    labour_rates: overrides.labour_rates ?? [
      {
        labour_subtype: 'sub-workshop',
        labour_subtype_name: 'Workshop',
        charge_out_rate: 100,
        is_workshop: true,
      } as unknown as Job['labour_rates'][number],
    ],
    has_actual_costset: overrides.has_actual_costset ?? true,
    leave_type: overrides.leave_type ?? null,
    estimated_hours: overrides.estimated_hours ?? null,
    default_xero_pay_item_id:
      overrides.default_xero_pay_item_id ?? '22222222-2222-2222-2222-222222222222',
    default_xero_pay_item_name: overrides.default_xero_pay_item_name ?? 'Ordinary Hours',
    shop_job: overrides.shop_job ?? false,
    is_urgent: overrides.is_urgent ?? false,
  } as Job
}

function makeEntry(): TimesheetCostLine {
  const now = new Date().toISOString()
  return {
    id: 'cost-line-1',
    kind: 'time',
    desc: '',
    quantity: 2,
    unit_cost: 40,
    unit_rev: 0,
    ext_refs: {},
    meta: { staff_id: 'staff-1', date: '2026-06-16', is_billable: true, wage_rate_multiplier: 1.0 },
    created_at: now,
    updated_at: now,
    accounting_date: '2026-06-16',
    xero_time_id: null,
    xero_expense_id: null,
    xero_last_modified: null,
    xero_last_synced: null,
    approved: false,
    xero_pay_item: null,
    total_cost: 0,
    total_rev: 0,
    job_id: '',
    job_number: 0,
    job_name: '',
    client_name: '',
    charge_out_rate: 0,
    wage_rate: 40,
    xero_pay_item_name: '',
    labour_subtype: null,
    labour_subtype_name: '',
  } as TimesheetCostLine
}

function mountTable(jobs: Job[], entries: TimesheetCostLine[]) {
  selectHandlers.length = 0
  return mount(SmartTimesheetTable, {
    props: {
      entries,
      staffId: 'staff-1',
      staffWageRate: 40,
      accountingDate: '2026-06-16',
      jobs,
    },
    global: {
      stubs: {
        HoursCell: true,
        TimesheetActionsCell: true,
        Textarea: true,
      },
    },
  })
}

function selectJob(job: Job): void {
  const handler = selectHandlers[0]
  expect(handler).toBeTypeOf('function')
  handler(job)
}

describe('SmartTimesheetTable bill multiplier reset on job switch', () => {
  beforeEach(() => {
    selectHandlers.length = 0
    for (const key of Object.keys(billHandlers)) delete billHandlers[key]
  })

  it('(a) defaults bill multiplier to 1.5 for an urgent job', async () => {
    const urgent = makeJob({ id: 'urgent-1', job_number: 200, is_urgent: true })
    const entry = makeEntry()
    const wrapper = mountTable([urgent], [entry])

    selectJob(urgent)
    await wrapper.vm.$nextTick()

    expect(getBillMultiplier(entry)).toBe(1.5)
    expect(entry.unit_rev).toBe(150)
  })

  it('(b) resets bill multiplier to 1.0 when switching an unsaved row from urgent to non-urgent', async () => {
    const urgent = makeJob({ id: 'urgent-1', job_number: 200, is_urgent: true })
    const normal = makeJob({ id: 'normal-1', job_number: 201, is_urgent: false })
    const entry = makeEntry()
    const wrapper = mountTable([urgent, normal], [entry])

    selectJob(urgent)
    await wrapper.vm.$nextTick()
    expect(getBillMultiplier(entry)).toBe(1.5)

    selectJob(normal)
    await wrapper.vm.$nextTick()

    // The stale 1.5x from the urgent job must reset to 1.0 for the non-urgent job.
    expect(getBillMultiplier(entry)).toBe(1.0)
    expect(entry.unit_rev).toBe(100)
  })

  it('(c) preserves an explicit user setBill override across a job switch', async () => {
    const jobA = makeJob({ id: 'a-1', job_number: 300, is_urgent: false })
    const jobB = makeJob({ id: 'b-1', job_number: 301, is_urgent: false })
    const entry = makeEntry()
    const wrapper = mountTable([jobA, jobB], [entry])

    selectJob(jobA)
    await wrapper.vm.$nextTick()

    // Simulate a genuine user bill-rate choice of 2.0x through the Invoice
    // dropdown on the saved entry's row (row 0; the phantom row is separate).
    const billHandler = billHandlers['billRate-0']
    expect(billHandler).toBeTypeOf('function')
    billHandler('2.0')
    await wrapper.vm.$nextTick()
    expect(getBillMultiplier(entry)).toBe(2.0)

    // Switching to another job must NOT clobber the explicit override.
    selectJob(jobB)
    await wrapper.vm.$nextTick()

    expect(getBillMultiplier(entry)).toBe(2.0)
    expect(entry.unit_rev).toBe(200)
  })
})
