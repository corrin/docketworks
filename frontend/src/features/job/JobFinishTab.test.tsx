import { http, HttpResponse } from 'msw/http'
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

  describe('deleting an approved invoice', () => {
    const approved = {
      id: 'invoice-1',
      xero_id: 'xero-invoice-1',
      number: 'INV-0101',
      status: 'AUTHORISED',
      date: '2026-10-01',
      due_date: null,
      total_excl_tax: 100,
      total_incl_tax: 115,
      amount_due: 115,
      tax: 15,
      online_url: null,
    }
    const reason =
      'INV-0101 is already approved so cannot be simply deleted. Would you like to void it, or just add a second invoice? Be very careful voiding it if it has been sent.'

    it('offers the void, and voids only when the user says so', async () => {
      stubQuietEndpoints()
      const voidFlags: (string | null)[] = []
      server.use(
        http.get('*/api/job/jobs/*/finish/', () => HttpResponse.json(finishPayload)),
        http.get('*/api/job/jobs/*/invoices/', () => HttpResponse.json({ invoices: [approved] })),
        http.delete('*/api/xero/delete_invoice/*', ({ request }) => {
          const flag = new URL(request.url).searchParams.get('void_approved')
          voidFlags.push(flag)
          return flag === 'true'
            ? HttpResponse.json({
                success: true,
                xero_id: 'xero-invoice-1',
                message: 'Invoice voided.',
              })
            : HttpResponse.json(
                { success: false, error: reason, error_type: 'invoice_approved' },
                { status: 400 },
              )
        }),
      )

      const { user } = renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)
      await user.click(await screen.findByRole('button', { name: 'Delete invoice INV-0101' }))

      expect(await screen.findByText(reason)).toBeInTheDocument()
      expect(voidFlags).toEqual(['false'])

      await user.click(autoId('JobInvoiceCard-void-offer-void'))

      await waitFor(() => expect(voidFlags).toEqual(['false', 'true']))
    })

    it('shows any other refusal as it came, with no void offer', async () => {
      stubQuietEndpoints()
      const requests: (string | null)[] = []
      server.use(
        http.get('*/api/job/jobs/*/finish/', () => HttpResponse.json(finishPayload)),
        http.get('*/api/job/jobs/*/invoices/', () => HttpResponse.json({ invoices: [approved] })),
        http.delete('*/api/xero/delete_invoice/*', ({ request }) => {
          requests.push(new URL(request.url).searchParams.get('void_approved'))
          return HttpResponse.json(
            { success: false, error: 'Invoice not of valid status for modification' },
            { status: 400 },
          )
        }),
      )

      const { user } = renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)
      await user.click(await screen.findByRole('button', { name: 'Delete invoice INV-0101' }))

      expect(await screen.findByText('Invoice not of valid status for modification')).toBeVisible()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(requests).toEqual(['false'])
    })

    it('cancelling the offer sends nothing, and says why a second invoice is unavailable', async () => {
      stubQuietEndpoints()
      const requests: (string | null)[] = []
      server.use(
        http.get('*/api/job/jobs/*/finish/', () =>
          HttpResponse.json({
            ...finishPayload,
            summary: { ...finishPayload.summary, remaining_to_invoice_excl_gst: '0.00' },
          }),
        ),
        http.get('*/api/job/jobs/*/invoices/', () => HttpResponse.json({ invoices: [approved] })),
        http.delete('*/api/xero/delete_invoice/*', ({ request }) => {
          requests.push(new URL(request.url).searchParams.get('void_approved'))
          return HttpResponse.json(
            { success: false, error: reason, error_type: 'invoice_approved' },
            { status: 400 },
          )
        }),
      )

      const { user } = renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)
      await user.click(await screen.findByRole('button', { name: 'Delete invoice INV-0101' }))
      await screen.findByText(reason)

      expect(autoId('JobInvoiceCard-void-offer-second-invoice')).toBeDisabled()
      expect(autoId('JobInvoiceCard-void-offer-second-invoice')).toHaveAttribute(
        'title',
        'Everything on this job is already invoiced, so there is nothing left for a second invoice.',
      )

      await user.click(screen.getByRole('button', { name: 'Cancel' }))

      await waitFor(() => expect(screen.queryByText(reason)).not.toBeInTheDocument())
      expect(requests).toEqual(['false'])
    })

    it('keeps a voided invoice on the job with its delete button off', async () => {
      stubQuietEndpoints()
      server.use(
        http.get('*/api/job/jobs/*/finish/', () => HttpResponse.json(finishPayload)),
        http.get('*/api/job/jobs/*/invoices/', () =>
          HttpResponse.json({ invoices: [{ ...approved, status: 'VOIDED' }] }),
        ),
      )

      renderWithProviders(<JobFinishTab jobId="job-1" job={baseJob} />)

      const remove = await screen.findByRole('button', { name: 'Delete invoice INV-0101' })
      expect(remove).toBeDisabled()
      expect(remove).toHaveAttribute(
        'title',
        'Already voided in Xero. It stays on the job so its history is complete.',
      )
    })
  })
})
