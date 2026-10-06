import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import { TimesheetHistoryDialog } from './TimesheetHistoryDialog'

const HISTORY = '*/api/job/timesheet/entries/history/'

const moved = {
  id: 'event-1',
  timestamp: '2026-10-01T02:30:00Z',
  event_type: 'entry_moved',
  staff_name: 'Olivia Office',
  description: "Moved from #101 to #202. Charge-out $/h changed from '120.00' to '200.00'",
  changes: [
    { field_name: 'Job', old_value: '#101', new_value: '#202' },
    { field_name: 'Charge-out $/h', old_value: '120.00', new_value: '200.00' },
  ],
  before: null,
  after: null,
}

describe('TimesheetHistoryDialog', () => {
  it("lists the day's events with who, when, what, and the change rows", async () => {
    let requested = ''
    server.use(
      http.get(HISTORY, ({ request }) => {
        requested = new URL(request.url).search
        return HttpResponse.json([moved])
      }),
    )

    renderWithProviders(
      <TimesheetHistoryDialog staffId="staff-1" date="2026-10-01" open onClose={vi.fn()} />,
    )

    expect(await screen.findByText('Olivia Office')).toBeInTheDocument()
    expect(screen.getByText(/Moved from #101 to #202/)).toBeInTheDocument()
    expect(screen.getByText('Charge-out $/h')).toBeInTheDocument()
    expect(requested).toBe('?staff_id=staff-1&date=2026-10-01')
  })

  it('says so when the day has no history', async () => {
    server.use(http.get(HISTORY, () => HttpResponse.json([])))

    renderWithProviders(
      <TimesheetHistoryDialog staffId="staff-1" date="2026-10-01" open onClose={vi.fn()} />,
    )

    expect(await screen.findByText('No history recorded yet.')).toBeInTheDocument()
  })
})
