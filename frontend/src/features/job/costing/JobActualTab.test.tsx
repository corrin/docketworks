import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobActualTab } from './JobActualTab'

function stubTabData() {
  server.use(
    http.get('*/api/job/jobs/job-1/', () =>
      HttpResponse.json({
        success: true,
        data: {
          job: { id: 'job-1' },
          company_defaults: { materials_markup: 0.2, time_markup: 0.3, wage_rate: 38 },
        },
      }),
    ),
    http.get('*/api/job/jobs/*/cost_sets/actual/', () =>
      HttpResponse.json({
        cost_lines: [],
        created: '2026-08-09T00:00:00Z',
        id: 'cost-set-actual',
        job: 'job-1',
        kind: 'actual',
        rev: 0,
        summary: { cost: 1137.33, rev: 1840, hours: 9, profitMargin: 38.2 },
      }),
    ),
    http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json([])),
  )
}

describe('JobActualTab', () => {
  it('renders the grid and the server-owned Time & Expenses chip', async () => {
    stubTabData()

    renderWithProviders(<JobActualTab jobId="job-1" />)

    await screen.findByRole('heading', { name: 'Actual Costs' })
    await waitFor(() => {
      expect(document.querySelector('.smart-costlines-table')).not.toBeNull()
    })
    // The chip renders summary.rev verbatim (ADR 0046) — the cost-entry spec
    // asserts it equals the sum of the actual lines' total_rev, which the
    // server guarantees, never client arithmetic.
    const chip = document.querySelector('[data-automation-id="JobActualTab-time-expenses"]')
    expect(chip).toHaveTextContent('$1,840.00')
  })

  it('shows the full server-owned summary beside the grid', async () => {
    stubTabData()

    renderWithProviders(<JobActualTab jobId="job-1" />)

    await screen.findByRole('heading', { name: 'Actual Summary' })
    const summary = document.querySelector('[data-automation-id="JobActualTab-summary"]')
    expect(summary).toHaveTextContent('$1,840.00')
    expect(summary).toHaveTextContent('$1,137.33')
    expect(summary).toHaveTextContent('9')
    expect(summary).toHaveTextContent('38.2%')
  })
})
