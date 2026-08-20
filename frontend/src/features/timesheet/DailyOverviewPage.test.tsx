import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { DailyOverviewPage } from './DailyOverviewPage'

const FRIDAY = '2026-08-07'

const summaryPayload = {
  date: FRIDAY,
  staff_data: [
    {
      staff_id: 'staff-1',
      staff_name: 'Wendy Workshop',
      staff_initials: 'WW',
      icon_url: null,
      scheduled_hours: 8,
      actual_hours: 6,
      billable_hours: 6,
      non_billable_hours: 0,
      total_revenue: 720,
      total_cost: 288,
      day_status: 'Partial',
      billable_percentage: 100,
      completion_percentage: 75,
      job_breakdown: [],
      entry_count: 2,
      alerts: [],
      is_weekend: false,
      weekend_enabled: false,
    },
  ],
  daily_totals: {
    total_scheduled_hours: 8,
    total_actual_hours: 6,
    total_billable_hours: 6,
    total_non_billable_hours: 0,
    total_revenue: 720,
    total_cost: 288,
    total_entries: 2,
    completion_percentage: 75,
    billable_percentage: 100,
    missing_hours: 2,
  },
  summary_stats: {
    total_staff: 1,
    complete_staff: 0,
    partial_staff: 1,
    missing_staff: 0,
    completion_rate: 0,
  },
  weekend_enabled: false,
  is_weekend: false,
}

function renderPage() {
  server.use(http.get('*/api/timesheets/daily/*', () => HttpResponse.json(summaryPayload)))
  const onDateChange = vi.fn()
  const onOpenEntry = vi.fn()
  renderWithProviders(
    <DailyOverviewPage
      search={{ date: FRIDAY }}
      onDateChange={onDateChange}
      onOpenEntry={onOpenEntry}
    />,
  )
  return { onDateChange, onOpenEntry }
}

function autoId(id: string): HTMLElement {
  const el = document.querySelector(`[data-automation-id="${id}"]`)
  if (!(el instanceof HTMLElement)) throw new Error(`missing element ${id}`)
  return el
}

function nextDayButton(): HTMLElement {
  const el = document.querySelector('[aria-label="Next day"]')
  if (!(el instanceof HTMLElement)) throw new Error('missing Next day button')
  return el
}

describe('DailyOverviewPage', () => {
  it('renders a StaffRow per staff member with the automation-id contract', async () => {
    renderPage()
    await waitFor(() => autoId('StaffRow-row-staff-1'))
    expect(autoId('StaffRow-name-staff-1')).toHaveTextContent('Wendy Workshop')
  })

  it('clicking the staff name opens the entry page for that staff and date', async () => {
    const { onOpenEntry } = renderPage()
    const user = userEvent.setup()
    await waitFor(() => autoId('StaffRow-name-staff-1'))
    await user.click(autoId('StaffRow-name-staff-1'))
    expect(onOpenEntry).toHaveBeenCalledWith('staff-1', FRIDAY)
  })

  it('next-day navigation is a plain +1 day (no weekend skip on this page)', async () => {
    const { onDateChange } = renderPage()
    const user = userEvent.setup()
    await waitFor(() => expect(document.querySelector('[aria-label="Next day"]')).toBeTruthy())
    await user.click(nextDayButton())
    expect(onDateChange).toHaveBeenCalledWith('2026-08-08')
  })
})
