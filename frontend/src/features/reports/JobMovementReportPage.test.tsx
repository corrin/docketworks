import { http, HttpResponse } from 'msw'
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobMovementReportPage } from './JobMovementReportPage'

const movementResponse = {
  period: { start_date: '2026-07-27', end_date: '2026-08-09', days: 14 },
  metrics: {
    draft_jobs_created: { count: 7 },
    quotes_submitted: { count: 5 },
    quotes_accepted: { count: 3 },
    jobs_won: { count: 2, still_draft: 1, rejected: 1, total_created: 7 },
    draft_conversion_rate: { rate: 28.6, numerator: 2, denominator: 7 },
    quote_acceptance_rate: { rate: 60, numerator: 3, denominator: 5 },
    workflow_paths: {
      through_quotes: 2,
      skip_quotes: 1,
      still_draft: 1,
      quote_usage_percent: 66.7,
    },
  },
}

describe('JobMovementReportPage', () => {
  it('renders counts and rates from the parsed response', async () => {
    server.use(
      http.get('*/api/accounting/reports/job-movement/', () => HttpResponse.json(movementResponse)),
    )
    const { container } = renderWithProviders(<JobMovementReportPage />)

    expect(await screen.findByText('28.6%')).toBeVisible()
    expect(
      container.querySelector('[data-automation-id="JobMovementReport-draft-jobs-count"]'),
    ).toHaveTextContent('7')
    expect(
      container.querySelector('[data-automation-id="JobMovementReport-jobs-won-count"]'),
    ).toHaveTextContent('2')
    expect(screen.getByText('60.0%')).toBeVisible()
  })

  it('fails loudly when the schemaless response drifts from the pinned shape', async () => {
    server.use(
      http.get('*/api/accounting/reports/job-movement/', () =>
        HttpResponse.json({ metrics: { draft_jobs_created: { count: 'seven' } } }),
      ),
    )
    renderWithProviders(<JobMovementReportPage />)

    expect(await screen.findByText('Failed to load the job movement report.')).toBeVisible()
  })
})
