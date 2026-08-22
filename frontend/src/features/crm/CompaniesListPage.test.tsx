import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { CompaniesListPage } from './CompaniesListPage'

import type { CompanySearchResponse, CompanySearchResult } from '@/api'

const company = (overrides: Partial<CompanySearchResult> = {}): CompanySearchResult => ({
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
  ...overrides,
})

const envelope = (
  results: CompanySearchResult[],
  overrides: Partial<CompanySearchResponse> = {},
): CompanySearchResponse => ({
  count: results.length,
  page: 1,
  page_size: 50,
  results,
  total_pages: 1,
  ...overrides,
})

describe('CompaniesListPage', () => {
  it('lists companies and re-sorts on the server when the header is clicked', async () => {
    const sortParams: string[] = []
    server.use(
      http.get('*/api/companies/search/', ({ request }) => {
        const url = new URL(request.url)
        sortParams.push(`${url.searchParams.get('sort_by')}:${url.searchParams.get('sort_dir')}`)
        return HttpResponse.json(envelope([company()]))
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
    // not shuffle the rows the page happens to hold.
    await user.click(screen.getByRole('button', { name: 'Total Spend' }))
    await waitFor(() => expect(sortParams).toContain('total_spend:asc'))
    await user.click(screen.getByRole('button', { name: 'Total Spend' }))
    await waitFor(() => expect(sortParams).toContain('total_spend:desc'))
  })

  it('appends the next page on Load more and resets to one page on re-sort', async () => {
    const requests: string[] = []
    server.use(
      http.get('*/api/companies/search/', ({ request }) => {
        const url = new URL(request.url)
        const page = url.searchParams.get('page')
        requests.push(`${url.searchParams.get('sort_by')}:${page}`)
        if (page === '2') {
          return HttpResponse.json(
            envelope([company({ id: 'c-2', name: 'Beta Fabrication' })], {
              count: 2,
              page: 2,
              total_pages: 2,
            }),
          )
        }
        return HttpResponse.json(envelope([company()], { count: 2, total_pages: 2 }))
      }),
    )
    const { user } = renderWithProviders(<CompaniesListPage />)

    expect(await screen.findByText('Alpha Engineering')).toBeVisible()
    expect(screen.getByText('Showing 1 of 2 companies')).toBeVisible()
    // The server's page size applies; the page does not carry its own.
    expect(requests).toEqual(['name:1'])

    await user.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('Beta Fabrication')).toBeVisible()
    expect(screen.getByText('Alpha Engineering')).toBeVisible()
    expect(screen.getByText('Showing 2 of 2 companies')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()

    // A new sort is a new list: back to page one, second page dropped.
    await user.click(screen.getByRole('button', { name: 'Total Spend' }))
    await waitFor(() => expect(requests).toEqual(['name:1', 'name:2', 'total_spend:1']))
    await waitFor(() => expect(screen.queryByText('Beta Fabrication')).toBeNull())
    expect(screen.getByText('Showing 1 of 2 companies')).toBeVisible()
  })
})
