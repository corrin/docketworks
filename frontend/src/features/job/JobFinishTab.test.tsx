import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { JobDetail, JobFinishResponse } from '@/api'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobFinishTab } from './JobFinishTab'

const baseJob: JobDetail = {
  company_id: null,
  company_name: null,
  created_at: '2026-08-08T00:00:00Z',
  default_xero_pay_item_id: null,
  default_xero_pay_item_name: null,
  delivery_date: null,
  description: null,
  fully_invoiced: false,
  id: 'job-1',
  invoices: [],
  is_urgent: false,
  job_files: [],
  job_is_valid: true,
  job_number: 1,
  job_status: 'draft',
  latest_actual: null,
  latest_estimate: null,
  latest_quote: null,
  max_people: 1,
  min_people: 1,
  name: 'Test job',
  notes: null,
  order_number: null,
  paid: false,
  person_id: null,
  person_name: null,
  price_cap: null,
  pricing_methodology: 'fixed_price',
  quote: null,
  quote_acceptance_date: null,
  quote_sheet: null,
  quoted: false,
  rdti_type: null,
  rejected_flag: false,
  shop_job: false,
  speed_quality_tradeoff: 'normal',
  updated_at: '2026-08-08T00:00:00Z',
  xero_invoices: [],
  xero_quote: null,
}

const finishPayload: JobFinishResponse = {
  summary: {
    job_value_excl_gst: '1000.00',
    valid_invoiced_excl_gst: '0.00',
    outstanding_invoiced_incl_gst: '0.00',
    remaining_to_invoice_excl_gst: '1000.00',
    remaining_gst: '150.00',
    remaining_to_invoice_incl_gst: '1150.00',
    total_to_pay_incl_gst: '1150.00',
    over_invoiced_excl_gst: '0.00',
  },
  checklist: {
    foreman_signed_off: false,
    timesheets_collected: false,
    materials_checked: false,
    customer_called: false,
    released: false,
  },
}

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
