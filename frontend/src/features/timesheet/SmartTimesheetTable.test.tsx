import { act, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { TimesheetCostLineOut, TimesheetJobOut, XeroPayItemOut } from '@/api'
import { renderWithProviders } from '@/test/render'
import { SmartTimesheetTable, type SmartTimesheetTableProps } from './SmartTimesheetTable'

const STAFF_ID = 'staff-1'
const DATE = '2026-08-10'

const workshopRate = {
  id: 'rate-1',
  labour_subtype: 'subtype-workshop',
  labour_subtype_name: 'Workshop',
  is_workshop: true,
  charge_out_rate: '120.00',
}

function makeJob(overrides: Partial<TimesheetJobOut> = {}): TimesheetJobOut {
  return {
    id: 'job-1',
    job_number: 101,
    name: 'Fabricate frame',
    company_name: 'ABC Carpet Cleaning TEST IGNORE',
    status: 'in_progress',
    labour_rates: [workshopRate],
    has_actual_costset: true,
    leave_type: null,
    estimated_hours: null,
    default_xero_pay_item_id: 'pay-ordinary',
    default_xero_pay_item_name: 'Ordinary Time',
    shop_job: false,
    is_urgent: false,
    ...overrides,
  }
}

const normalJob = makeJob()
const urgentJob = makeJob({ id: 'job-2', job_number: 202, name: 'Emergency gate', is_urgent: true })

const payItems: XeroPayItemOut[] = [
  {
    id: 'pay-ordinary',
    xero_id: 'x1',
    xero_tenant_id: 't',
    name: 'Ordinary Time',
    uses_leave_api: false,
    multiplier: 1,
    xero_last_modified: null,
    xero_last_synced: null,
    created_at: '2026-08-10T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
  },
  {
    id: 'pay-double',
    xero_id: 'x2',
    xero_tenant_id: 't',
    name: 'Double Time',
    uses_leave_api: false,
    multiplier: 2,
    xero_last_modified: null,
    xero_last_synced: null,
    created_at: '2026-08-10T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
  },
]

function makeLine(overrides: Partial<TimesheetCostLineOut> = {}): TimesheetCostLineOut {
  return {
    id: 'line-1',
    kind: 'time',
    desc: 'Cutting',
    quantity: '3.500',
    unit_cost: '48.00',
    unit_rev: '120.00',
    ext_refs: {},
    meta: {
      staff_id: STAFF_ID,
      date: DATE,
      is_billable: true,
      wage_rate_multiplier: 1,
      bill_rate_multiplier: 1,
      created_from_timesheet: true,
    },
    created_at: '2026-08-10T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
    accounting_date: DATE,
    xero_time_id: null,
    xero_expense_id: null,
    xero_last_modified: null,
    xero_last_synced: null,
    approved: true,
    xero_pay_item: 'pay-ordinary',
    staff: STAFF_ID,
    entry_seq: 1,
    labour_subtype: 'subtype-workshop',
    total_cost: 168,
    total_rev: 420,
    job_id: 'job-1',
    job_number: 101,
    job_name: 'Fabricate frame',
    company_name: 'ABC Carpet Cleaning TEST IGNORE',
    ...overrides,
  }
}

function autoId(id: string): HTMLElement {
  const el = document.querySelector(`[data-automation-id="${id}"]`)
  if (!(el instanceof HTMLElement)) throw new Error(`missing element ${id}`)
  return el
}

async function renderTable(props: Partial<SmartTimesheetTableProps> = {}) {
  const handles = {
    patchLine: vi.fn(),
    createLine: vi.fn(),
    deleteLine: vi.fn(),
    approveLine: vi.fn(),
  }
  renderWithProviders(
    <SmartTimesheetTable
      entries={[]}
      jobs={[normalJob, urgentJob]}
      payItems={payItems}
      staffId={STAFF_ID}
      date={DATE}
      staffWageRate={48}
      {...handles}
      {...props}
    />,
  )
  await waitFor(() => autoId('DataTable-row-0'))
  return handles
}

describe('salary rate', () => {
  it('labels salary allocation without offering an overtime pay selector', async () => {
    await renderTable({ payBasis: 'salary' })

    expect(document.body).toHaveTextContent('Salary')
    expect(document.querySelector('[data-automation-id="SmartTimesheetTable-rate-0"]')).toBeNull()
  })
})

async function pickJob(
  user: ReturnType<typeof userEvent.setup>,
  rowIndex: number,
  jobNumber: number,
) {
  await user.click(autoId(`SmartTimesheetTable-jobPicker-${rowIndex}-trigger`))
  await waitFor(() => autoId(`SmartTimesheetTable-jobPicker-${rowIndex}-option-${jobNumber}`))
  await user.click(autoId(`SmartTimesheetTable-jobPicker-${rowIndex}-option-${jobNumber}`))
}

describe('rows and the phantom invariant', () => {
  it('renders server rows then exactly one trailing phantom with continuous indices', async () => {
    await renderTable({ entries: [makeLine()] })
    expect(autoId('DataTable-row-0')).toHaveAttribute('data-row-id', 'line-1')
    expect(autoId('DataTable-row-1').getAttribute('data-row-id')).toBeTruthy()
    expect(document.querySelectorAll('[data-automation-id^="DataTable-row-"]')).toHaveLength(2)
  })

  it('renders humanised hours as the input value on server rows', async () => {
    await renderTable({ entries: [makeLine()] })
    expect(autoId('SmartTimesheetTable-hours-0')).toHaveValue('3h 30m')
  })

  it('locks the picker and money cells for server rows', async () => {
    await renderTable({ entries: [makeLine()] })
    expect(autoId('SmartTimesheetTable-jobPicker-0-trigger')).toBeDisabled()
    expect(autoId('SmartTimesheetTable-wage-0')).toHaveTextContent('$168.00')
    expect(autoId('SmartTimesheetTable-bill-0')).toHaveTextContent('$420.00')
  })

  it('resolves the hidden pay-item span from the pay-items list', async () => {
    await renderTable({ entries: [makeLine({ xero_pay_item: 'pay-double' })] })
    expect(autoId('SmartTimesheetTable-payItem-0')).toHaveTextContent('Double Time')
  })
})

describe('creating an entry', () => {
  it('picking a job moves focus to the hours cell', async () => {
    const user = userEvent.setup()
    await renderTable()
    await pickJob(user, 0, 101)
    await waitFor(() => expect(autoId('SmartTimesheetTable-hours-0')).toHaveFocus())
  })

  it('Enter in hours creates with the exact meta contract', async () => {
    const user = userEvent.setup()
    const handles = await renderTable()
    await pickJob(user, 0, 101)
    await waitFor(() => expect(autoId('SmartTimesheetTable-hours-0')).toHaveFocus())
    await user.keyboard('2{Enter}')
    expect(handles.createLine).toHaveBeenCalledTimes(1)
    const [job, body] = handles.createLine.mock.calls[0]!
    expect(job.id).toBe('job-1')
    expect(body.quantity).toBe('2')
    expect(body.meta).toEqual({
      staff_id: STAFF_ID,
      date: DATE,
      is_billable: true,
      wage_rate_multiplier: 1,
      bill_rate_multiplier: 1,
      created_from_timesheet: true,
    })
  })

  it('an urgent job creates with bill 1.5 and wage 1.0, and shows the urgent affordances', async () => {
    const user = userEvent.setup()
    const handles = await renderTable()
    await user.click(autoId('SmartTimesheetTable-jobPicker-0-trigger'))
    await waitFor(() => autoId('SmartTimesheetTable-jobPicker-0-option-202'))
    expect(autoId('SmartTimesheetTable-jobPicker-0-option-202')).toHaveTextContent('URGENT')
    await user.click(autoId('SmartTimesheetTable-jobPicker-0-option-202'))
    await waitFor(() =>
      expect(autoId('SmartTimesheetTable-urgentBadge-0')).toHaveTextContent('Urgent'),
    )
    expect(autoId('SmartTimesheetTable-jobPicker-0-trigger')).toHaveTextContent('!')
    expect(autoId('SmartTimesheetTable-rate-0')).toHaveTextContent('Ord')
    expect(autoId('SmartTimesheetTable-billRate-0')).toHaveTextContent('1.5x')
    await user.click(autoId('SmartTimesheetTable-hours-0'))
    await user.keyboard('2{Enter}')
    const [, body] = handles.createLine.mock.calls[0]!
    expect(body.meta.wage_rate_multiplier).toBe(1.0)
    expect(body.meta.bill_rate_multiplier).toBe(1.5)
    expect(body.meta.is_billable).toBe(true)
  })

  it('Tab from hours defers the create until description commits', async () => {
    const user = userEvent.setup()
    const handles = await renderTable()
    await pickJob(user, 0, 101)
    await waitFor(() => expect(autoId('SmartTimesheetTable-hours-0')).toHaveFocus())
    await user.keyboard('2')
    await user.tab()
    // Focus moved within the row: no create yet.
    expect(handles.createLine).not.toHaveBeenCalled()
    await waitFor(() => expect(autoId('SmartTimesheetTable-description-0')).toHaveFocus())
    await user.keyboard('Cutting')
    await user.tab()
    await waitFor(() => expect(handles.createLine).toHaveBeenCalledTimes(1))
    const [, body] = handles.createLine.mock.calls[0]!
    expect(body.desc).toBe('Cutting')
    expect(body.quantity).toBe('2')
  })

  it('the next phantom picker is disabled while the create is in flight, and focus lands in the new phantom after it settles', async () => {
    const user = userEvent.setup()
    const settle: Array<() => void> = []
    const createLine = vi.fn(
      (
        _job: TimesheetJobOut,
        _body: unknown,
        cb: { onCreated: (line: TimesheetCostLineOut) => void },
      ) => {
        settle.push(() => cb.onCreated(makeLine({ id: 'line-new' })))
      },
    )
    await renderTable({ createLine })
    await pickJob(user, 0, 101)
    await waitFor(() => expect(autoId('SmartTimesheetTable-hours-0')).toHaveFocus())
    await user.keyboard('2{Enter}')
    expect(createLine).toHaveBeenCalledTimes(1)
    // In flight: the NEXT phantom's trigger is disabled.
    expect(autoId('SmartTimesheetTable-jobPicker-1-trigger')).toBeDisabled()
    act(() => settle[0]!())
    // The committed draft leaves the grid (entries stay static in this test,
    // so the fresh phantom is now row 0) and the focus handoff opens its
    // picker with the search focused.
    await waitFor(() => expect(autoId('SmartTimesheetTable-jobPicker-0-trigger')).toBeEnabled())
    await waitFor(() => expect(autoId('SmartTimesheetTable-jobPicker-0-search')).toHaveFocus())
  })
})

describe('saved-row edits', () => {
  it('description Enter commits a PATCH with desc only', async () => {
    const user = userEvent.setup()
    const handles = await renderTable({ entries: [makeLine()] })
    await user.click(autoId('SmartTimesheetTable-description-0'))
    await user.keyboard('{Control>}a{/Control}new words{Enter}')
    await waitFor(() => expect(handles.patchLine).toHaveBeenCalledTimes(1))
    expect(handles.patchLine.mock.calls[0]![0]).toBe('line-1')
    expect(handles.patchLine.mock.calls[0]![1]).toEqual({ desc: 'new words' })
  })

  it('an hours edit patches quantity plus meta (the reprice trigger)', async () => {
    const user = userEvent.setup()
    const handles = await renderTable({ entries: [makeLine()] })
    await user.click(autoId('SmartTimesheetTable-hours-0'))
    await user.keyboard('4{Enter}')
    await waitFor(() => expect(handles.patchLine).toHaveBeenCalledTimes(1))
    const [, body] = handles.patchLine.mock.calls[0]!
    expect(body.quantity).toBe('4')
    expect(body.meta).toMatchObject({ created_from_timesheet: true })
  })

  it('approve and delete buttons drive their handles', async () => {
    const user = userEvent.setup()
    const handles = await renderTable({ entries: [makeLine({ approved: false })] })
    await user.click(autoId('SmartTimesheetTable-actions-0-approve'))
    expect(handles.approveLine).toHaveBeenCalledWith('line-1')
    await user.click(autoId('SmartTimesheetTable-actions-0-delete'))
    expect(handles.deleteLine).toHaveBeenCalledWith('line-1')
  })
})
