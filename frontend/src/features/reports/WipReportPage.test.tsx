import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { WipReportPage } from './WipReportPage'

const wipResponse = {
  report_date: '2026-08-08',
  method: 'revenue',
  summary: {
    total_gross: 1234.5,
    total_invoiced: 200,
    total_net: -987.65,
    job_count: 1,
    by_status: [],
  },
  jobs: [
    {
      job_number: 42,
      name: 'Test job',
      company: 'Test company',
      gross_wip: 1234.5,
      invoiced: 200,
      net_wip: -987.65,
      adjust_cost: 0,
      adjust_rev: 0,
      material_cost: 0,
      material_rev: 0,
      labour_cost: 0,
      labour_rev: 0,
      status: 'in_progress',
      status_display: 'In Progress',
    },
  ],
  archived_jobs: [],
}

describe('WipReportPage', () => {
  it('renders the summary values through the shared formatter', async () => {
    server.use(http.get('*/api/accounting/reports/wip/', () => HttpResponse.json(wipResponse)))
    const { container } = renderWithProviders(<WipReportPage />)

    // findAllByText because the same formatted values appear in the table
    // rows as well as the summary cards.
    await screen.findAllByText('$1,234.50')
    expect(
      container.querySelector('[data-automation-id="WIPReport-total-gross-value"]'),
    ).toHaveTextContent('$1,234.50')
    expect(
      container.querySelector('[data-automation-id="WIPReport-total-net-value"]'),
    ).toHaveTextContent('-$987.65')
    // The loading marker must UNMOUNT (not hide): the E2E contract waits on
    // state hidden, which requires the element to leave the tree.
    await waitFor(() =>
      expect(container.querySelector('[data-automation-id="WIPReport-loading"]')).toBeNull(),
    )
    expect(
      container.querySelectorAll('[data-automation-id="WIPReport-table"] tbody tr'),
    ).toHaveLength(1)
  })

  it('reports failure with a retry instead of rendering empty cards', async () => {
    let attempts = 0
    server.use(
      http.get('*/api/accounting/reports/wip/', () => {
        attempts += 1
        return attempts === 1
          ? HttpResponse.json({ detail: 'unavailable' }, { status: 503 })
          : HttpResponse.json(wipResponse)
      }),
    )
    const { user } = renderWithProviders(<WipReportPage />)

    expect(await screen.findByText('Failed to load the WIP report.')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await screen.findAllByText('$1,234.50')
  })
})
