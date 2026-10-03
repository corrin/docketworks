import { http, HttpResponse } from 'msw'
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { autoId, queryAutoId } from '@/test/auto-id'
import { crmJobRow, jobInvoiceRef } from '@/test/crmJobRow'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { RelatedJobsTable } from './RelatedJobsTable'

describe('RelatedJobsTable', () => {
  it('lists each job with its invoices, links, and the invoiced total', async () => {
    server.use(
      http.get('*/api/people/p-1/jobs/', () =>
        HttpResponse.json({
          results: [
            crmJobRow({
              job_id: 'job-1',
              job_number: 101,
              name: 'Fabricate frame',
              invoices: [
                jobInvoiceRef({
                  id: 'inv-1',
                  number: 'INV-0001',
                  date: '2026-02-20',
                  total_excl_tax: 100,
                }),
                jobInvoiceRef({
                  id: 'inv-2',
                  number: 'INV-0002',
                  date: '2026-03-05',
                  total_excl_tax: 25.5,
                  online_url: null,
                }),
              ],
              invoiced_total_excl_tax: 125.5,
            }),
            crmJobRow({
              job_id: 'job-2',
              job_number: 102,
              name: 'Weld bracket',
              company: { id: 'company-2', name: 'Beta Fabrication' },
            }),
          ],
        }),
      ),
    )
    renderWithProviders(
      <RelatedJobsTable
        owner={{ kind: 'person', personId: 'p-1' }}
        automationId="PersonDetail-jobs"
        showCompany
      />,
    )

    const jobLink = await screen.findByRole('link', { name: '#101 Fabricate frame' })
    expect(jobLink).toHaveAttribute('href', '/jobs/job-1')
    expect(screen.getByRole('link', { name: 'Alpha Engineering' })).toHaveAttribute(
      'href',
      '/crm/companies/company-1',
    )
    const firstInvoice = autoId('PersonDetail-jobs-invoice-inv-1')
    expect(firstInvoice).toHaveTextContent('INV-0001')
    expect(firstInvoice).toHaveTextContent('20 Feb 2026')
    expect(firstInvoice.querySelector('a')).toHaveAttribute(
      'href',
      'https://invoices.example/inv-1',
    )
    // No Xero link yet: the number is text, not a dead anchor.
    expect(autoId('PersonDetail-jobs-invoice-inv-2').querySelector('a')).toBeNull()
    expect(autoId('PersonDetail-jobs-cell-job-1-invoiced')).toHaveTextContent('$125.50')
    expect(autoId('PersonDetail-jobs-row-job-2')).toHaveTextContent('Not invoiced')
    expect(autoId('PersonDetail-jobs-cell-job-2-invoiced')).toHaveTextContent('$0.00')
    expect(autoId('PersonDetail-jobs-total')).toHaveTextContent('$125.50')
    expect(queryAutoId('PersonDetail-jobs-row-job-1')).not.toBeNull()
  })

  it('omits the company column on the company page', async () => {
    server.use(
      http.get('*/api/people/p-1/jobs/', () => HttpResponse.json({ results: [crmJobRow()] })),
    )
    renderWithProviders(
      <RelatedJobsTable
        owner={{ kind: 'person', personId: 'p-1' }}
        automationId="CompanyDetail-jobs"
        showCompany={false}
      />,
    )

    await screen.findByRole('link', { name: '#101 Fabricate frame' })
    expect(screen.queryByRole('link', { name: 'Alpha Engineering' })).toBeNull()
    expect(screen.queryByRole('columnheader', { name: 'Company' })).toBeNull()
  })
})
