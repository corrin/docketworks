import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw/http'
import { describe, expect, it, vi } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import { FillDaySheet } from './FillDaySheet'

const JOB = { id: 'job-1', job_number: 42, name: 'Handrail', company_name: 'ABC' }
const FILL = { break_hours: 0.5, entered_hours: 0, to_fill_hours: 7.5, to_go_hours: 7.5 }

function serve(overtimeHours: number) {
  const asked: URLSearchParams[] = []
  server.use(
    http.get('*/api/job/jobs/status-choices/', () => HttpResponse.json({ statuses: {} })),
    http.get('*/api/timesheets/jobs/', () =>
      HttpResponse.json({
        jobs: [JOB],
        total_count: 1,
        pinned_job_ids: [JOB.id],
        recent_job_ids: [],
      }),
    ),
    http.get('*/api/timesheets/my-day/placement/', ({ request }) => {
      asked.push(new URL(request.url).searchParams)
      return HttpResponse.json({
        start: '07:00:00',
        finish: '16:00:00',
        hours: 9,
        overtime_hours: overtimeHours,
      })
    }),
  )
  return asked
}

async function fillNineHours() {
  const onSend = vi.fn().mockResolvedValue(true)
  renderWithProviders(
    <FillDaySheet
      open
      date="2026-05-04"
      fill={FILL}
      sending={false}
      onSend={onSend}
      onClose={() => {}}
    />,
  )
  fireEvent.click(await screen.findByText('#42 Handrail'))
  fireEvent.click(screen.getByText('4h'))
  for (let step = 0; step < 20; step++)
    fireEvent.click(screen.getByLabelText('Quarter of an hour more'))
  fireEvent.click(screen.getByText('Send to office'))
  return { onSend }
}

describe('FillDaySheet', () => {
  // Owner, 2026-10-26: Joe marks his own overtime, so he is told before the
  // hours past his usual day go as time and a half, as the entry drawer tells him.
  it('asks before sending hours that run past his usual day, then sends them', async () => {
    const asked = serve(1)
    const { onSend } = await fillNineHours()

    expect(await screen.findByText(/1h of this is past your usual day/)).toBeTruthy()
    expect(onSend).not.toHaveBeenCalled()
    expect(asked.map((query) => query.get('hours'))).toEqual(['9'])

    fireEvent.click(screen.getByText('Send with overtime'))
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1))
  })

  it('sends at once when nothing runs past his usual day', async () => {
    serve(0)
    const { onSend } = await fillNineHours()

    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1))
    expect(screen.queryByText(/past your usual day/)).toBeNull()
  })
})
