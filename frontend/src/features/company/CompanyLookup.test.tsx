import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CompanySearchResult } from '@/api'
import { expectNoAccessibilityViolations } from '@/test/accessibility'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { CompanyLookup } from './CompanyLookup'

const companies: CompanySearchResult[] = [
  {
    id: 'company-1',
    name: 'Alpha Engineering',
    address: '',
    allow_jobs: true,
    email: '',
    is_account_customer: true,
    is_supplier: false,
    last_invoice_date: null,
    phone: '',
    total_spend: '0',
    xero_contact_id: 'xero-1',
  },
  {
    id: 'company-2',
    name: 'Alpine Fabrication',
    address: '',
    allow_jobs: true,
    email: '',
    is_account_customer: true,
    is_supplier: false,
    last_invoice_date: null,
    phone: '',
    total_spend: '0',
    xero_contact_id: 'xero-2',
  },
]

describe('CompanyLookup', () => {
  it('supports the combobox keyboard contract and exposes deferred create honestly', async () => {
    server.use(
      http.get('*/api/companies/search/', () =>
        HttpResponse.json({ count: 2, page: 1, page_size: 20, results: companies, total_pages: 1 }),
      ),
    )
    const onSelectCompany = vi.fn()
    const { container, user } = renderWithProviders(
      <CompanyLookup
        id="company"
        label="Company"
        selectedCompany={null}
        onSelectCompany={onSelectCompany}
      />,
    )

    const input = await screen.findByRole('combobox', { name: 'Company' })
    await user.type(input, 'Alp')
    await screen.findByRole('option', { name: 'Alpha Engineering' })

    expect(input).toHaveAttribute('aria-expanded', 'true')
    await waitFor(() =>
      expect(input).toHaveAttribute('aria-activedescendant', expect.stringContaining('company-1')),
    )
    expect(screen.getByText(/Add new company/).closest('[aria-disabled]')).toHaveAttribute(
      'aria-disabled',
      'true',
    )

    await user.keyboard('{ArrowDown}{Enter}')

    expect(onSelectCompany).toHaveBeenCalledWith(companies[1])
    expect(input).toHaveFocus()
    expect(input).toHaveAttribute('aria-expanded', 'false')
    await expectNoAccessibilityViolations(container)
  })
})
