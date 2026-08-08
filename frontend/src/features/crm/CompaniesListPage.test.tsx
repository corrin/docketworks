import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { CompaniesListPage } from './CompaniesListPage'

const results = [
  {
    id: 'c-1',
    name: 'Alpha Engineering',
    email: 'office@alpha.example',
    phone: '021 555 000',
    address: '',
    is_account_customer: false,
    is_supplier: false,
    allow_jobs: true,
    xero_contact_id: 'x-1',
    last_invoice_date: null,
    total_spend: 1234.5,
  },
]

describe('CompaniesListPage', () => {
  it('lists companies and re-sorts on the server when the header is clicked', async () => {
    const sortParams: string[] = []
    server.use(
      http.get('*/api/companies/search/', ({ request }) => {
        const url = new URL(request.url)
        sortParams.push(`${url.searchParams.get('sort_by')}:${url.searchParams.get('sort_dir')}`)
        return HttpResponse.json({ results })
      }),
    )
    const { container, user } = renderWithProviders(<CompaniesListPage />)

    expect(await screen.findByText('Alpha Engineering')).toBeVisible()
    const spendCell = container.querySelector(
      '[data-automation-id="CompaniesTable-cell-c-1-total-spend"]',
    )
    expect(spendCell).toHaveTextContent('$1,234.50')
    const row = container.querySelector('[data-automation-id="CompaniesTable-row-c-1"]')
    expect(row).toHaveAttribute('data-company-id', 'c-1')

    // Sorting is a server concern: the click must change the request params,
    // not shuffle the 20 rows the page happens to hold.
    await user.click(screen.getByRole('button', { name: 'Total Spend' }))
    await waitFor(() => expect(sortParams).toContain('total_spend:asc'))
    await user.click(screen.getByRole('button', { name: 'Total Spend' }))
    await waitFor(() => expect(sortParams).toContain('total_spend:desc'))
  })
})
