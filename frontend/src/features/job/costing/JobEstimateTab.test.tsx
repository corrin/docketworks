import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobEstimateTab } from './JobEstimateTab'

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
    http.get('*/api/job/jobs/*/cost_sets/estimate/', () =>
      HttpResponse.json({
        cost_lines: [],
        created: '2026-08-09T00:00:00Z',
        id: 'cost-set-est',
        job: 'job-1',
        kind: 'estimate',
        rev: 0,
        summary: { cost: 0, rev: 0, hours: 0, profitMargin: null },
      }),
    ),
    http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json([])),
  )
}

describe('JobEstimateTab', () => {
  it('renders the estimate grid for any pricing methodology', async () => {
    stubTabData()

    renderWithProviders(<JobEstimateTab jobId="job-1" />)

    await screen.findByText('Estimate Details')
    await waitFor(() => {
      expect(document.querySelector('.smart-costlines-table')).not.toBeNull()
    })
  })
})
