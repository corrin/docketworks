import { http, HttpResponse } from 'msw'
import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { SalesForecastPage } from './SalesForecastPage'

const FORECAST_URL = '*/api/accounting/reports/sales-forecast/'
const JUNE_DETAIL_URL = '*/api/accounting/reports/sales-forecast/2026-06/'

const forecastResponse = {
  months: [
    {
      month: '2026-07',
      month_label: 'Jul 2026',
      xero_sales: 1000,
      jm_sales: 900,
      variance: 100,
      variance_pct: 10,
    },
    {
      month: '2026-06',
      month_label: 'Jun 2026',
      xero_sales: 500,
      jm_sales: 700,
      variance: -200,
      variance_pct: -40,
    },
  ],
}

function detailRow(overrides: Record<string, unknown>) {
  return {
    date: '2026-06-02',
    company_name: 'Miller-Mcpherson',
    job_number: 97176,
    job_name: 'CUT WATER TANK',
    job_id: '73933669-5f44-413c-962c-3954f948492f',
    job_start_date: '2026-06-01',
    invoice_numbers: 'INV-56076',
    total_invoiced: 253,
    job_revenue: 165,
    variance: 88,
    note: null,
    total_xero_all_time: 253,
    total_jm_all_time: 165,
    variance_all_time: 88,
    ...overrides,
  }
}

const juneDetail = {
  month: '2026-06',
  month_label: 'Jun 2026',
  rows: [
    detailRow({ company_name: 'Zeta Engineering' }),
    detailRow({
      company_name: 'Alpha Fabrication',
      job_id: null,
      job_number: null,
      job_name: null,
      job_start_date: null,
      total_invoiced: 0,
      job_revenue: 133.26,
      variance: -133.26,
      variance_all_time: null,
    }),
  ],
}

function serveForecast() {
  server.use(
    http.get(FORECAST_URL, () => HttpResponse.json(forecastResponse)),
    http.get(JUNE_DETAIL_URL, () => HttpResponse.json(juneDetail)),
  )
}

/** Automation ids are the E2E contract, so the unit test drives the same
    handles rather than role or text queries that only it can use. */
function element(container: HTMLElement, automationId: string): HTMLElement {
  const found = container.querySelector(`[data-automation-id="${automationId}"]`)
  if (!(found instanceof HTMLElement)) throw new Error(`missing ${automationId}`)
  return found
}

/** By automation id, not column position — an inserted column would move a
    positional read onto different data without failing (ADR 0025). */
function companyColumn(container: HTMLElement): string[] {
  return [
    ...container.querySelectorAll('[data-automation-id="SalesForecastReport-detail-company"]'),
  ].map((cell) => cell.textContent ?? '')
}

describe('SalesForecastPage', () => {
  it('totals the months into the summary cards through the shared formatters', async () => {
    serveForecast()
    const { container } = renderWithProviders(<SalesForecastPage />)

    await screen.findByText('Jul 2026')
    expect(
      container.querySelector('[data-automation-id="SalesForecastReport-xero-sales-value"]'),
    ).toHaveTextContent('$1,500.00')
    expect(
      container.querySelector('[data-automation-id="SalesForecastReport-jm-sales-value"]'),
    ).toHaveTextContent('$1,600.00')
    expect(
      container.querySelector('[data-automation-id="SalesForecastReport-variance-value"]'),
    ).toHaveTextContent('-$100.00')
    // The mean of the monthly percentages, NOT a percentage of the totals:
    // a month that invoiced nothing must weigh the same as a busy one.
    expect(
      container.querySelector('[data-automation-id="SalesForecastReport-avg-variance-value"]'),
    ).toHaveTextContent('-15.0%')

    // The loading marker must UNMOUNT (not hide): the E2E contract waits on
    // state hidden, which requires the element to leave the tree.
    await waitFor(() =>
      expect(
        container.querySelector('[data-automation-id="SalesForecastReport-loading"]'),
      ).toBeNull(),
    )
  })

  it('drills into a month and back out again', async () => {
    serveForecast()
    const { container, user } = renderWithProviders(<SalesForecastPage />)

    const juneRow = await screen.findByText('Jun 2026')
    await user.click(juneRow)

    await screen.findByText('Zeta Engineering')
    expect(
      container.querySelector('[data-automation-id="SalesForecastReport-detail-month"]'),
    ).toHaveTextContent('Jun 2026')
    // An unmatched row has no job to link to, and a job revenue of zero is an
    // em dash rather than $0.00.
    const unmatched = screen.getByText('Alpha Fabrication').closest('tr')
    if (!(unmatched instanceof HTMLElement)) throw new Error('missing unmatched row')
    expect(within(unmatched).queryByRole('link')).toBeNull()

    await user.click(element(container, 'SalesForecastReport-back'))
    await screen.findByText('Jul 2026')
    expect(
      container.querySelector('[data-automation-id="SalesForecastReport-detail-table"]'),
    ).toBeNull()
  })

  it('sorts detail rows on the clicked column, keeping blanks last both ways', async () => {
    serveForecast()
    const { container, user } = renderWithProviders(<SalesForecastPage />)

    await user.click(await screen.findByText('Jun 2026'))
    await screen.findByText('Zeta Engineering')

    const companyHeader = within(
      element(container, 'SalesForecastReport-header-company'),
    ).getByRole('button')
    await user.click(companyHeader)
    await waitFor(() =>
      expect(companyColumn(container)).toEqual(['Alpha Fabrication', 'Zeta Engineering']),
    )

    await user.click(companyHeader)
    await waitFor(() =>
      expect(companyColumn(container)).toEqual(['Zeta Engineering', 'Alpha Fabrication']),
    )

    // Job Start is null on the unmatched row: it sits last ascending AND
    // descending, so reversing the sort never buries the data under blanks.
    // The company sort above left Alpha first, so a Job Start sort that did
    // nothing would leave it there — this asserts a change, not a coincidence.
    await user.click(companyHeader)
    await waitFor(() =>
      expect(companyColumn(container)).toEqual(['Alpha Fabrication', 'Zeta Engineering']),
    )

    const startHeader = within(
      element(container, 'SalesForecastReport-header-job-start'),
    ).getByRole('button')
    await user.click(startHeader)
    await waitFor(() =>
      expect(companyColumn(container)).toEqual(['Zeta Engineering', 'Alpha Fabrication']),
    )
    await user.click(startHeader)
    expect(companyColumn(container)).toEqual(['Zeta Engineering', 'Alpha Fabrication'])
  })

  it('reports failure with a retry instead of rendering empty cards', async () => {
    let attempts = 0
    server.use(
      http.get(FORECAST_URL, () => {
        attempts += 1
        return attempts === 1
          ? HttpResponse.json({ detail: 'unavailable' }, { status: 503 })
          : HttpResponse.json(forecastResponse)
      }),
    )
    const { user } = renderWithProviders(<SalesForecastPage />)

    expect(await screen.findByText('Failed to load the sales forecast.')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await screen.findByText('Jul 2026')
  })
})
