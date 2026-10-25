import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw/http'
import { describe, expect, it, vi } from 'vitest'

import type { WorkshopTimesheetEntryOut, WorkshopTimesheetEntryUpdateRequest } from '@/api'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import { WorkshopTimesheetEntryDrawer } from './WorkshopTimesheetEntryDrawer'

const entry: WorkshopTimesheetEntryOut = {
  id: 'entry-1',
  job_id: 'job-1',
  job_number: 42,
  job_name: 'Handrail',
  company_name: 'ABC',
  description: 'Welding',
  hours: 2,
  accounting_date: '2026-05-04',
  start_time: '09:00:00',
  end_time: '11:00:00',
  is_billable: true,
  wage_rate_multiplier: 1,
  bill_rate_multiplier: 1,
  approved: false,
  entered_late: false,
  remote_entry: false,
  created_at: '2026-05-04T21:00:00Z',
  updated_at: '2026-05-04T21:00:00Z',
}

describe('WorkshopTimesheetEntryDrawer', () => {
  // M4: a double tap on Save is one write. The server does not de-duplicate
  // two identical saves (two jobs at the same times is an ordinary pair, W2),
  // so the drawer's in-flight guard is the whole of the protection.
  it('M4: a double tap on Save sends one save', async () => {
    server.use(
      http.get('*/api/timesheets/jobs/', () =>
        HttpResponse.json({ jobs: [], total_count: 0, pinned_job_ids: [], recent_job_ids: [] }),
      ),
    )
    // Never settles: the first save is still on its way when the taps land.
    const onUpdate = vi.fn(
      (_body: WorkshopTimesheetEntryUpdateRequest) => new Promise<boolean>(() => undefined),
    )

    renderWithProviders(
      <WorkshopTimesheetEntryDrawer
        state={{ mode: 'edit', entry }}
        locked={false}
        date="2026-05-04"
        dayEntries={[entry]}
        dayStart="07:00"
        dayEnd="15:00"
        saving={false}
        onCreate={vi.fn()}
        onUpdate={onUpdate}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    const save = await screen.findByRole('button', { name: 'Save changes' })

    fireEvent.click(save)
    fireEvent.click(save)
    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1))
    // A third tap while that save is still pending is refused on the spot.
    fireEvent.click(save)

    expect(onUpdate).toHaveBeenCalledTimes(1)
  })
})
