import { http, HttpResponse } from 'msw'
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { CompanyDetailPage } from './CompanyDetailPage'

const company = {
  id: 'c-1',
  name: 'Alpha Engineering',
  address: '1 Foundry Lane',
  email: 'office@alpha.example',
  phone: '021 555 000',
  total_spend: 1234.5,
  last_invoice_date: null,
}

describe('CompanyDetailPage', () => {
  it('shows the financial summary behind a real tab switch', async () => {
    server.use(http.get('*/api/companies/c-1/', () => HttpResponse.json(company)))
    const { container, user } = renderWithProviders(<CompanyDetailPage companyId="c-1" />)

    expect(await screen.findByRole('heading', { name: 'Alpha Engineering' })).toBeVisible()
    // Contact tab first: the spec's Financial Summary click must be a real
    // tab change, not a no-op on an already-active tab.
    expect(screen.getByText('1 Foundry Lane')).toBeVisible()

    await user.click(screen.getByRole('tab', { name: 'Financial Summary' }))

    const spend = container.querySelector('[data-automation-id="CompanyDetail-total-spend"]')
    expect(spend).toHaveTextContent('$1,234.50')
    expect(screen.getByText('No invoices')).toBeVisible()
  })
})
