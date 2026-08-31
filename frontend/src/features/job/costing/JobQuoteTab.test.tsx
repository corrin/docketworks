import { http, HttpResponse } from 'msw'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { JobDetail } from '@/api'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobQuoteTab } from './JobQuoteTab'

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

function stubTabData() {
  server.use(
    http.get('*/api/job/jobs/job-1/', () =>
      HttpResponse.json({
        success: true,
        data: {
          job: baseJob,
          company_defaults: { materials_markup: 0.2, time_markup: 0.3, wage_rate: 38 },
        },
      }),
    ),
    http.get('*/api/job/jobs/*/cost_sets/quote/', () =>
      HttpResponse.json({
        cost_lines: [],
        created: '2026-08-09T00:00:00Z',
        id: 'cost-set-1',
        job: 'job-1',
        kind: 'quote',
        rev: 2,
        summary: { cost: 1137.33, rev: 1840, hours: 9, profitMargin: 38.2 },
      }),
    ),
    http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json([])),
    http.get('*/api/job/jobs/*/quote/', () => HttpResponse.json({ quote: null })),
    http.get('*/api/xero/ping/', () =>
      HttpResponse.json({ connected: true, xero_readonly: false, xero_production_client: false }),
    ),
  )
}

describe('JobQuoteTab', () => {
  it('shows the server-owned summary verbatim beside the grid', async () => {
    stubTabData()

    renderWithProviders(<JobQuoteTab jobId="job-1" job={baseJob} />)

    await screen.findByText('$1,840.00')
    const summary = document.querySelector('[data-automation-id="JobQuoteTab-summary"]')
    expect(summary).toHaveTextContent('$1,840.00')
    expect(summary).toHaveTextContent('$1,137.33')
    expect(summary).toHaveTextContent('38.2%')
    // The grid arrived in quote mode alongside it.
    expect(document.querySelector('.smart-costlines-table')).not.toBeNull()
  })

  it('copies the estimate in one press when the server accepts', async () => {
    stubTabData()
    const bodies: unknown[] = []
    server.use(
      http.post('*/api/job/jobs/*/cost_sets/quote/copy_from_estimate/', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({
          success: true,
          message: 'Estimate copied to quote.',
          copied_cost_lines_count: 3,
          archived_quote_revision: null,
          job_id: 'job-1',
        })
      }),
    )
    const user = userEvent.setup()

    renderWithProviders(<JobQuoteTab jobId="job-1" job={baseJob} />)

    await user.click(await screen.findByRole('button', { name: /Copy from Estimate/ }))

    await screen.findByText('Estimate copied to quote.')
    expect(bodies).toEqual([{ archive_existing: false }])
    // No dialog on the happy path: a blank quote is replaced without ceremony.
    expect(screen.queryByRole('button', { name: /Archive & replace/ })).toBeNull()
  })

  it('offers archive-and-replace when the server refuses a priced quote', async () => {
    stubTabData()
    const bodies: unknown[] = []
    server.use(
      http.post('*/api/job/jobs/*/cost_sets/quote/copy_from_estimate/', async ({ request }) => {
        bodies.push(await request.json())
        // First press refuses (priced quote); the dialog's re-post succeeds.
        if (bodies.length === 1) {
          return HttpResponse.json(
            { detail: 'The quote already has priced cost lines.' },
            { status: 409 },
          )
        }
        return HttpResponse.json({
          success: true,
          message: 'Estimate copied to quote.',
          copied_cost_lines_count: 3,
          archived_quote_revision: 1,
          job_id: 'job-1',
        })
      }),
    )
    const user = userEvent.setup()

    renderWithProviders(<JobQuoteTab jobId="job-1" job={baseJob} />)

    await user.click(await screen.findByRole('button', { name: /Copy from Estimate/ }))
    await user.click(await screen.findByRole('button', { name: /Archive & replace/ }))

    // findAll: sonner keeps the previous test's identical toast in the DOM.
    await screen.findAllByText('Estimate copied to quote.')
    expect(bodies).toEqual([{ archive_existing: false }, { archive_existing: true }])
  })

  it('lists archived revisions in the history dialog', async () => {
    stubTabData()
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/revise/', () =>
        HttpResponse.json({
          job_id: 'job-1',
          job_number: 1,
          current_cost_set_rev: 2,
          total_revisions: 1,
          revisions: [
            {
              quote_revision: 1,
              archived_at: '2026-08-30T02:15:00+00:00',
              reason: 'customer changed scope',
              summary: { cost: 180, rev: 360, hours: 2 },
              cost_lines: [
                {
                  id: 'line-1',
                  kind: 'material',
                  desc: 'Sheet steel',
                  quantity: 1,
                  unit_cost: 100,
                  unit_rev: 150,
                  total_cost: 100,
                  total_rev: 150,
                  ext_refs: {},
                  meta: {},
                },
              ],
            },
          ],
        }),
      ),
    )
    const user = userEvent.setup()

    renderWithProviders(<JobQuoteTab jobId="job-1" job={baseJob} />)

    await user.click(await screen.findByRole('button', { name: /Revisions/ }))

    await screen.findByText('Quote Revisions History')
    expect(screen.getByText(/Revision 1/)).toBeInTheDocument()
    expect(screen.getByText('customer changed scope')).toBeInTheDocument()
    expect(screen.getByText('$360.00')).toBeInTheDocument()
    expect(screen.getByText('Sheet steel')).toBeInTheDocument()
  })

  it('refuses to render a quote workspace for a T&M job', async () => {
    stubTabData()
    const tmJob: JobDetail = { ...baseJob, pricing_methodology: 'time_materials' }

    renderWithProviders(<JobQuoteTab jobId="job-1" job={tmJob} />)

    expect(await screen.findByText(/time and materials job has no quote/i)).toBeInTheDocument()
    expect(document.querySelector('.smart-costlines-table')).toBeNull()
  })
})
