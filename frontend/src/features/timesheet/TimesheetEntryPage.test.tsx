import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { TimesheetEntryPage, type TimesheetEntrySearch } from './TimesheetEntryPage'

const STAFF_ID = 'staff-1'
const FRIDAY = '2026-08-07'

const staffPayload = {
  staff: [
    {
      id: STAFF_ID,
      name: 'Wendy Workshop',
      firstName: 'Wendy',
      lastName: 'Workshop',
      email: 'wendy@example.com',
      icon_url: null,
      wageRate: '48.00',
    },
  ],
  total_count: 1,
}

const jobsPayload = { jobs: [], total_count: 0 }

function entriesPayload(lines: unknown[]) {
  return {
    cost_lines: lines,
    staff: { id: STAFF_ID, name: 'Wendy Workshop', first_name: 'Wendy', last_name: 'Workshop' },
    date: FRIDAY,
    summary: {
      total_hours: 0,
      billable_hours: 0,
      non_billable_hours: 0,
      total_cost: 0,
      total_revenue: 0,
      entry_count: lines.length,
      scheduled_hours: 8,
    },
  }
}

function line(id: string, quantity: string, isBillable: boolean, totalRev: number) {
  return {
    id,
    kind: 'time',
    desc: '',
    quantity,
    unit_cost: '48.00',
    unit_rev: '120.00',
    ext_refs: {},
    meta: {
      staff_id: STAFF_ID,
      date: FRIDAY,
      is_billable: isBillable,
      created_from_timesheet: true,
    },
    created_at: '2026-08-07T00:00:00Z',
    updated_at: '2026-08-07T00:00:00Z',
    accounting_date: FRIDAY,
    xero_time_id: null,
    xero_expense_id: null,
    xero_last_modified: null,
    xero_last_synced: null,
    approved: true,
    xero_pay_item: null,
    staff: STAFF_ID,
    entry_seq: 1,
    labour_subtype: null,
    total_cost: 96,
    total_rev: totalRev,
    job_id: 'job-1',
    job_number: 101,
    job_name: 'Fabricate frame',
    company_name: 'ABC',
  }
}

function installHandlers(options: { weekendEnabled?: boolean; lines?: unknown[] } = {}) {
  server.use(
    http.get('*/api/timesheets/staff/', () => HttpResponse.json(staffPayload)),
    http.get('*/api/timesheets/jobs/', () => HttpResponse.json(jobsPayload)),
    http.get('*/api/xero/pay-items/', () => HttpResponse.json([])),
    http.get('*/api/company-defaults/', () =>
      HttpResponse.json({ weekend_timesheets_enabled: options.weekendEnabled ?? false }),
    ),
    http.get('*/api/job/timesheet/entries/', () =>
      HttpResponse.json(entriesPayload(options.lines ?? [])),
    ),
  )
}

function renderPage(search: TimesheetEntrySearch) {
  const onSearchChange = vi.fn()
  const onOpenDaily = vi.fn()
  renderWithProviders(
    <TimesheetEntryPage
      search={search}
      onSearchChange={onSearchChange}
      onOpenDaily={onOpenDaily}
    />,
  )
  return { onSearchChange, onOpenDaily }
}

function nextDayButton(): HTMLElement {
  const el = document.querySelector('[aria-label="Next day"]')
  if (!(el instanceof HTMLElement)) throw new Error('missing Next day button')
  return el
}

describe('TimesheetEntryPage', () => {
  it('renders the grid with no lingering spinner once loaded', async () => {
    installHandlers()
    renderPage({ date: FRIDAY, staffId: STAFF_ID })
    await waitFor(() => expect(document.querySelector('.smart-timesheet-table')).toBeTruthy())
    expect(document.querySelector('.animate-spin')).toBeNull()
  })

  it('fails loudly for a staffId outside the timesheet staff list', async () => {
    installHandlers()
    renderPage({ date: FRIDAY, staffId: 'ghost-staff' })
    await waitFor(() =>
      expect(document.body.textContent).toContain(
        'Staff ghost-staff is not available for timesheet entry',
      ),
    )
  })

  it('skips the weekend on next-day navigation when weekend timesheets are disabled', async () => {
    installHandlers({ weekendEnabled: false })
    const { onSearchChange } = renderPage({ date: FRIDAY, staffId: STAFF_ID })
    const user = userEvent.setup()
    await waitFor(() => expect(document.querySelector('[aria-label="Next day"]')).toBeTruthy())
    await user.click(nextDayButton())
    expect(onSearchChange).toHaveBeenCalledWith({ date: '2026-08-10', staffId: STAFF_ID })
  })

  it('computes the daily breakdown from the loaded entries', async () => {
    installHandlers({ lines: [line('a', '2.000', true, 240), line('b', '1.000', false, 0)] })
    renderPage({ date: FRIDAY, staffId: STAFF_ID })
    // The tiles render zeros while entries are in flight; wait for the money.
    await waitFor(() => expect(document.body.textContent).toContain('$240.00'))
    expect(document.body.textContent).toContain('3h')
  })
})
