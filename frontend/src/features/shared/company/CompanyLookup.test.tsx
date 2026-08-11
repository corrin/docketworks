import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CompanyCreateResponse, CompanySearchResult } from '@/api'
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
    total_spend: 0,
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
    total_spend: 0,
    xero_contact_id: 'xero-2',
  },
]

const createdCompany: CompanySearchResult = {
  id: 'company-new',
  name: 'Fresh Co Test',
  address: '',
  allow_jobs: true,
  email: '',
  is_account_customer: false,
  is_supplier: false,
  last_invoice_date: null,
  phone: '',
  total_spend: 0,
  xero_contact_id: 'xero-new',
}

function createResponse(company: CompanySearchResult): CompanyCreateResponse {
  return { success: true, company, message: `Company "${company.name}" created successfully` }
}

function useSearchResults(results: CompanySearchResult[]) {
  server.use(
    http.get('*/api/companies/search/', () =>
      HttpResponse.json({
        count: results.length,
        page: 1,
        page_size: 20,
        results,
        total_pages: 1,
      }),
    ),
  )
}

describe('CompanyLookup', () => {
  it('supports the combobox keyboard contract', async () => {
    useSearchResults(companies)
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

    await user.keyboard('{ArrowDown}{Enter}')

    expect(onSelectCompany).toHaveBeenCalledWith(companies[1])
    expect(input).toHaveFocus()
    expect(input).toHaveAttribute('aria-expanded', 'false')
    await expectNoAccessibilityViolations(container)
  })

  it('quick-creates a company on Ctrl+Enter and selects it', async () => {
    useSearchResults([])
    let createBody: unknown = null
    server.use(
      http.post('*/api/companies/create/', async ({ request }) => {
        createBody = await request.json()
        return HttpResponse.json(createResponse(createdCompany), { status: 201 })
      }),
    )
    const onSelectCompany = vi.fn()
    const { user } = renderWithProviders(
      <CompanyLookup
        id="company"
        label="Company"
        selectedCompany={null}
        onSelectCompany={onSelectCompany}
      />,
    )

    const input = await screen.findByRole('combobox', { name: 'Company' })
    await user.type(input, 'Fresh Co Test')
    await screen.findByText('No companies found')

    await user.keyboard('{Control>}{Enter}{/Control}')

    await waitFor(() => expect(onSelectCompany).toHaveBeenCalledWith(createdCompany))
    expect(createBody).toEqual({ name: 'Fresh Co Test', is_account_customer: false })
  })

  it('surfaces a create failure without selecting anything', async () => {
    useSearchResults([])
    server.use(
      http.post('*/api/companies/create/', () =>
        HttpResponse.json({ detail: 'Xero is down' }, { status: 500 }),
      ),
    )
    const onSelectCompany = vi.fn()
    const { user } = renderWithProviders(
      <CompanyLookup
        id="company"
        label="Company"
        selectedCompany={null}
        onSelectCompany={onSelectCompany}
      />,
    )

    const input = await screen.findByRole('combobox', { name: 'Company' })
    await user.type(input, 'Fresh Co Test')
    await screen.findByText('No companies found')

    await user.keyboard('{Control>}{Enter}{/Control}')

    // sonner renders outside the component; the observable contract here is
    // that no selection happened and the input still holds the query.
    await waitFor(() => expect(input).toHaveValue('Fresh Co Test'))
    expect(onSelectCompany).not.toHaveBeenCalled()
  })

  it('opens the create modal from the dropdown row and selects the created company', async () => {
    useSearchResults([])
    server.use(
      http.post('*/api/companies/create/', () =>
        HttpResponse.json(createResponse(createdCompany), { status: 201 }),
      ),
    )
    const onSelectCompany = vi.fn()
    const { user } = renderWithProviders(
      <CompanyLookup
        id="company"
        label="Company"
        selectedCompany={null}
        onSelectCompany={onSelectCompany}
      />,
    )

    const input = await screen.findByRole('combobox', { name: 'Company' })
    await user.type(input, 'Fresh Co Test')
    await user.click(await screen.findByText(/Add new company/))

    const dialog = await screen.findByRole('dialog', { name: 'Add New Company' })
    expect(dialog).toBeInTheDocument()
    const nameInput = await screen.findByLabelText(/Company Name/)
    expect(nameInput).toHaveValue('Fresh Co Test')

    await user.click(screen.getByRole('button', { name: 'Create Company' }))

    await waitFor(() => expect(onSelectCompany).toHaveBeenCalledWith(createdCompany))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Add New Company' })).not.toBeInTheDocument(),
    )
  })

  it('keeps the modal open and shows the error when create fails', async () => {
    useSearchResults([])
    server.use(
      http.post('*/api/companies/create/', () =>
        HttpResponse.json(
          { detail: "Company 'Fresh Co Test' already exists in Xero with ID: abc" },
          { status: 400 },
        ),
      ),
    )
    const onSelectCompany = vi.fn()
    const { user } = renderWithProviders(
      <CompanyLookup
        id="company"
        label="Company"
        selectedCompany={null}
        onSelectCompany={onSelectCompany}
      />,
    )

    const input = await screen.findByRole('combobox', { name: 'Company' })
    await user.type(input, 'Fresh Co Test')
    await user.click(await screen.findByText(/Add new company/))
    await screen.findByRole('dialog', { name: 'Add New Company' })

    await user.click(screen.getByRole('button', { name: 'Create Company' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/already exists in Xero/)
    expect(onSelectCompany).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Add New Company' })).toBeInTheDocument()
  })
})
