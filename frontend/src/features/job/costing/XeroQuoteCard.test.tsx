import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { QuoteOut } from '@/api'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { XeroQuoteCard } from './XeroQuoteCard'

const quote: QuoteOut = {
  id: 'quote-1',
  xero_id: 'xero-quote-1',
  status: 'DRAFT',
  date: '2026-08-09',
  number: 'QU-0042',
  total_excl_tax: 1840,
  total_incl_tax: 2116,
  online_url: 'https://go.xero.com/app/quotes/edit/xero-quote-1',
}

function stubPing(connected: boolean) {
  server.use(
    http.get('*/api/xero/ping/', () =>
      HttpResponse.json({
        connected,
        xero_readonly: false,
        xero_production_client: false,
      }),
    ),
  )
}

function stubQuote(payload: QuoteOut | null) {
  server.use(http.get('*/api/job/jobs/*/quote/', () => HttpResponse.json({ quote: payload })))
}

describe('XeroQuoteCard', () => {
  it('disables creation with the login label when Xero is disconnected', async () => {
    stubPing(false)
    stubQuote(null)

    renderWithProviders(<XeroQuoteCard jobId="job-1" />)

    const button = await screen.findByRole('button', { name: 'Login to Xero first' })
    expect(button).toBeDisabled()
  })

  it('creates a total-only quote through the export dialog', async () => {
    stubPing(true)
    let created = false
    const bodies: unknown[] = []
    server.use(
      http.get('*/api/job/jobs/*/quote/', () =>
        HttpResponse.json({ quote: created ? quote : null }),
      ),
      http.post('*/api/xero/create_quote/*', async ({ request }) => {
        bodies.push(await request.json())
        created = true
        return HttpResponse.json(
          {
            success: true,
            xero_id: quote.xero_id,
            quote_id: quote.id,
            online_url: quote.online_url,
            messages: ['History note could not be added'],
          },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<XeroQuoteCard jobId="job-1" />)

    await user.click(await screen.findByRole('button', { name: 'Create Quote' }))
    expect(await screen.findByText('Export Quote to Xero')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Send Total Only/ }))

    await waitFor(() => expect(bodies).toEqual([{ breakdown: false }]))
    // Warnings ride the success response and each one is surfaced.
    expect(await screen.findByText('History note could not be added')).toBeInTheDocument()
    // The card re-reads the quote and offers the Xero deep link.
    expect(await screen.findByRole('button', { name: /Open in Xero/ })).toBeInTheDocument()
  })

  it('opens the quote in Xero without giving the new tab a window handle', async () => {
    stubPing(true)
    stubQuote(quote)
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const user = userEvent.setup()
    renderWithProviders(<XeroQuoteCard jobId="job-1" />)

    await user.click(await screen.findByRole('button', { name: /Open in Xero/ }))

    expect(openSpy).toHaveBeenCalledWith(quote.online_url, '_blank', 'noopener,noreferrer')
    openSpy.mockRestore()
  })

  it('deletes the quote and returns to the create state', async () => {
    stubPing(true)
    let deleted = false
    server.use(
      http.get('*/api/job/jobs/*/quote/', () =>
        HttpResponse.json({ quote: deleted ? null : quote }),
      ),
      http.delete('*/api/xero/delete_quote/*', () => {
        deleted = true
        return HttpResponse.json({
          success: true,
          xero_id: quote.xero_id,
          message: 'Quote deleted successfully.',
        })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderWithProviders(<XeroQuoteCard jobId="job-1" />)

    await user.click(await screen.findByRole('button', { name: 'Delete Quote' }))

    await waitFor(() => expect(deleted).toBe(true))
    expect(await screen.findByRole('button', { name: 'Create Quote' })).toBeInTheDocument()
  })

  it('surfaces the backend refusal text when creation fails', async () => {
    stubPing(true)
    stubQuote(null)
    server.use(
      http.post('*/api/xero/create_quote/*', () =>
        HttpResponse.json(
          {
            success: false,
            error: 'Configure Xero quote terms in Company Settings before creating a quote.',
            error_type: 'configuration_error',
          },
          { status: 400 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<XeroQuoteCard jobId="job-1" />)

    await user.click(await screen.findByRole('button', { name: 'Create Quote' }))
    await user.click(screen.getByRole('button', { name: /Send Breakdown/ }))

    expect(
      await screen.findByText(/Configure Xero quote terms in Company Settings/),
    ).toBeInTheDocument()
  })
})
