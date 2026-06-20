import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'
import { getBillMultiplier, getMultiplier, getRateTypeFromMultiplier } from '@/utils/timesheetCalc'

// The real autosave composable reaches into a Pinia store + the generated API
// client; this test only cares about the in-memory mutation setJob performs on
// the row, so stub the autosave layer to a no-op.
vi.mock('@/composables/useCostLineAutosave', () => ({
  useCostLineAutosave: () => ({
    scheduleSave: vi.fn(),
    clearStatus: vi.fn(),
  }),
}))

// Capture every onSelect handler the table wires onto a job picker so the test
// can invoke setJob the same way a user clicking a job in the picker would.
// `vi.hoisted` keeps the shared array accessible from the hoisted mock factory.
// billHandlers (keyed by row, e.g. 'billRate-0') lets the test drive setBill the
// way a user choosing an Invoice multiplier would — the only path that now marks
// an explicit customer-charge override.
const { selectHandlers, billHandlers } = vi.hoisted(() => ({
  selectHandlers: [] as Array<(job: unknown) => void>,
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

/**
 * A saved (has-id) row. setJob mutates this object in place via Object.assign,
 * so the test can hold a reference and read the result back after selecting a
 * job through the (stubbed) picker. The bill default does not depend on whether
 * the row is saved or phantom.
 */
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

/** Invoke the first row's job picker onSelect (the saved entry's picker). */
function selectJob(job: Job): void {
  const handler = selectHandlers[0]
  expect(handler).toBeTypeOf('function')
  handler(job)
}

describe('SmartTimesheetTable urgent charge default', () => {
  beforeEach(() => {
    selectHandlers.length = 0
    for (const key of Object.keys(billHandlers)) delete billHandlers[key]
  })

  it('defaults the customer charge to 1.5x and leaves the wage at Ordinary for an urgent billable job', async () => {
    const job = makeJob({ is_urgent: true })
    const entry = makeEntry()
    const wrapper = mountTable([job], [entry])

    selectJob(job)
    await wrapper.vm.$nextTick()

    expect(getBillMultiplier(entry)).toBe(1.5)
    expect(getMultiplier(entry)).toBe(1.0)
    expect(getRateTypeFromMultiplier(getBillMultiplier(entry))).toBe('1.5')
    // unit_rev = charge_out_rate (100) * 1.5
    expect(entry.unit_rev).toBe(150)

    // The Invoice dropdown reflects the 1.5x default (rendered via getBillMultiplier).
    expect(getRateTypeFromMultiplier(getBillMultiplier(entry))).toBe('1.5')
  })

  it('does not replace an explicit customer charge override when an urgent job is selected', async () => {
    // An override now means a deliberate setBill choice (a bare meta value is a
    // default, not an override). Establish the 2.0x choice via the Invoice
    // dropdown, then confirm selecting an urgent job leaves it untouched.
    const job = makeJob({ is_urgent: true })
    const entry = makeEntry()
    const wrapper = mountTable([job], [entry])

    const billHandler = billHandlers['billRate-0']
    expect(billHandler).toBeTypeOf('function')
    billHandler('2.0')
    await wrapper.vm.$nextTick()
    expect(getBillMultiplier(entry)).toBe(2.0)

    selectJob(job)
    await wrapper.vm.$nextTick()

    expect(getBillMultiplier(entry)).toBe(2.0)
    expect(getMultiplier(entry)).toBe(1.0)
    expect(getRateTypeFromMultiplier(getBillMultiplier(entry))).toBe('2.0')
    expect(entry.unit_rev).toBe(200)
  })

  it('renders an Urgent badge in the Job Name cell for a row linked to an urgent job', () => {
    const job = makeJob({ is_urgent: true })
    const entry = makeEntry()
    // Link the row to the urgent job up front so the badge renders on mount,
    // independent of in-place mutation reactivity.
    Object.assign(entry, { job_id: job.id, job_number: job.job_number, job_name: job.name })
    const wrapper = mountTable([job], [entry])

    expect(wrapper.find('[data-automation-id="SmartTimesheetTable-urgentBadge-0"]').exists()).toBe(
      true,
    )
    expect(wrapper.text()).toContain('Urgent')
  })

  it('renders no Urgent badge for a row linked to a non-urgent job', () => {
    const job = makeJob({ is_urgent: false })
    const entry = makeEntry()
    Object.assign(entry, { job_id: job.id, job_number: job.job_number, job_name: job.name })
    const wrapper = mountTable([job], [entry])

    expect(wrapper.find('[data-automation-id="SmartTimesheetTable-urgentBadge-0"]').exists()).toBe(
      false,
    )
  })

  it('leaves the bill multiplier at Ordinary for a non-urgent job and renders no badge', async () => {
    const job = makeJob({ is_urgent: false })
    const entry = makeEntry()
    const wrapper = mountTable([job], [entry])

    selectJob(job)
    await wrapper.vm.$nextTick()

    expect(getBillMultiplier(entry)).toBe(1.0)
    expect(getMultiplier(entry)).toBe(1.0)
    expect(entry.unit_rev).toBe(100)

    expect(wrapper.find('[data-automation-id="SmartTimesheetTable-urgentBadge-0"]').exists()).toBe(
      false,
    )
  })

  it('keeps bill at 0 for an urgent shop/non-billable job (the non-billable forcing wins)', async () => {
    const job = makeJob({ is_urgent: true, shop_job: true })
    const entry = makeEntry()
    const wrapper = mountTable([job], [entry])

    selectJob(job)
    await wrapper.vm.$nextTick()

    expect(getBillMultiplier(entry)).toBe(0)
    expect(entry.unit_rev).toBe(0)
  })
})
