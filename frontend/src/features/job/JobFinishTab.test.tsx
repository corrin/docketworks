import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { finishPayload, jobDetail } from '@/test/job'
import { autoId } from '@/test/auto-id'
import { seedJobViews } from '@/test/jobViews'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobFinishTab } from './JobFinishTab'

const baseJob = jobDetail()

function stubQuietEndpoints() {
  server.use(
    http.get('*/api/job/jobs/*/costs/summary/', () =>
      HttpResponse.json({ estimate: null, quote: null, actual: null }),
    ),
    http.get('*/api/job/jobs/*/invoices/', () => HttpResponse.json({ invoices: [] })),
    http.get('*/api/xero/ping/', () =>
      HttpResponse.json({ connected: true, xero_readonly: true, xero_production_client: false }),
    ),
  )
}

describe('JobFinishTab', () => {
  it('renders the server-owned balance verbatim', async () => {
    stubQuietEndpoints()
    server.use(http.get('*/api/job/jobs/*/finish/', () => HttpResponse.json(finishPayload)))

    renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)

    const totalToPay = await screen.findByText('$1,150.00')
    expect(totalToPay).toHaveAttribute('data-automation-id', 'JobFinishTab-total-to-pay')
    // Both the excl-GST remainder and GST come from the server, not local math.
    expect(screen.getAllByText('$1,000.00').length).toBeGreaterThan(0)
    expect(screen.getByText('$150.00')).toBeInTheDocument()
  })

  it('shows the load-error state instead of a settled $0 job when the balance fails', async () => {
    stubQuietEndpoints()
    server.use(
      http.get('*/api/job/jobs/*/finish/', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)

    expect(await screen.findByText("Could not load this job's financials.")).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('invalidates both job views after an invoice is created', async () => {
    stubQuietEndpoints()
    server.use(
      http.get('*/api/job/jobs/*/finish/', () => HttpResponse.json(finishPayload)),
      http.post('*/api/xero/create_invoice/*', () =>
        HttpResponse.json(
          { success: true, xero_id: 'xero-invoice-1', invoice_id: 'invoice-1', messages: [] },
          { status: 201 },
        ),
      ),
    )

    const { user, queryClient } = renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)
    await screen.findByText('$1,150.00')
    // Seeded after render: the tab's own queries are already registered, and
    // these two are the ones nothing on this screen reads.
    const keys = seedJobViews(queryClient, 'job-1')

    await user.click(await screen.findByRole('button', { name: 'Create Invoice' }))
    await user.click(autoId('JobFinishTab-mode-invoice-full'))

    // Creating an invoice writes a JobEvent and bumps the job's updated_at.
    await waitFor(() => {
      expect(queryClient.getQueryState(keys.timeline)?.isInvalidated).toBe(true)
      expect(queryClient.getQueryState(keys.job)?.isInvalidated).toBe(true)
    })
  })

  it('persists a checklist tick and hides the timesheets item on quoted jobs', async () => {
    stubQuietEndpoints()
    let patched: unknown = null
    server.use(
      http.get('*/api/job/jobs/*/finish/', () => HttpResponse.json(finishPayload)),
      http.patch('*/api/job/jobs/*/finish/', async ({ request }) => {
        patched = await request.json()
        return HttpResponse.json({
          ...finishPayload,
          checklist: { ...finishPayload.checklist, customer_called: true },
        })
      }),
    )

    const { user } = renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)

    const checkbox = await screen.findByLabelText('Have you called the customer?')
    // fixed_price: the timesheets question belongs to T&M jobs only.
    expect(screen.queryByLabelText("Have you collected today's timesheet entries?")).toBeNull()

    await user.click(checkbox)

    await waitFor(() => expect(patched).toEqual({ customer_called: true }))
    await waitFor(() => expect(checkbox).toBeChecked())
  })
})
