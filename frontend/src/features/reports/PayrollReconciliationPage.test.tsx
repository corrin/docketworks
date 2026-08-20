import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { PayrollReconciliationPage } from './PayrollReconciliationPage'

import type { PayrollStaffWeekRowOut, PayrollWeekReconciliationResponse } from '@/api'

const WEEK = '2026-08-17'
const ENDPOINT = '*/api/accounting/reports/payroll-reconciliation/week/'

function row(overrides: Partial<PayrollStaffWeekRowOut> = {}): PayrollStaffWeekRowOut {
  return {
    key: 'xero-emp-charlie',
    name: 'Charlie Nelson',
    xero_hours: 8,
    xero_timesheet_hours: 8,
    xero_leave_hours: 0,
    xero_gross: 320,
    xero_rate: 40,
    jm_hours: 8,
    jm_cost: 384, // priced at the LOADED rate: what the job was charged
    jm_rate: 48,
    jm_base_pay: 320, // the loading removed: what payroll owes
    pay_diff: 0,
    hours_diff: 0,
    cost_diff: 64,
    hours_cost_impact: 0,
    rate_cost_impact: 64,
    status: 'ok',
    ...overrides,
  }
}

function response(
  rows: PayrollStaffWeekRowOut[],
  xeroSource: PayrollWeekReconciliationResponse['xero_source'] = 'live_run',
): PayrollWeekReconciliationResponse {
  return {
    xero_source: xeroSource,
    // The count arrives computed: the status taxonomy lives on the server,
    // and the page renders this number verbatim.
    unposted_count: rows.filter(
      (r) => r.status.startsWith('xero_only_') && r.status !== 'xero_only_salaried',
    ).length,
    week: {
      week_start: WEEK,
      xero_period_start: null,
      xero_period_end: null,
      payment_date: null,
      totals: {
        xero_gross: rows.reduce((sum, r) => sum + r.xero_gross, 0),
        jm_cost: rows.reduce((sum, r) => sum + r.jm_cost, 0),
        diff: 0,
        xero_hours: 8,
        jm_hours: 8,
        // Deliberately NOT the sum of the rows. The page must render the
        // server's total verbatim, so a fixture whose total disagrees with its
        // own rows is what catches the browser re-summing them (ADR 0020).
        jm_base_pay: 1234.56,
        pay_diff: 0,
      },
      mismatch_count: rows.filter((r) => r.status !== 'ok').length,
      staff: rows,
    },
  }
}

describe('PayrollReconciliationPage', () => {
  it('shows the loading-free figure, never the job-costing one', async () => {
    // Opus: The whole page turns on this. jm_cost prices time at the loaded
    // rate (base + 20% annual leave loading) because that is what the job was
    // charged; Xero pays the base rate. Rendering jm_cost would show a
    // difference on every employee every week and bury the real ones.
    server.use(http.get(ENDPOINT, () => HttpResponse.json(response([row()]))))

    renderWithProviders(<PayrollReconciliationPage weekStart={WEEK} />)

    expect(await screen.findByText('Charlie Nelson')).toBeVisible()
    expect(screen.getAllByText('$320.00').length).toBeGreaterThan(0)
    expect(screen.queryByText('$384.00')).toBeNull()
  })

  it('renders the server total rather than re-summing the rows', async () => {
    // Opus: The fixture's total (1234.56) deliberately disagrees with the sum of
    // its rows (320.00). A page that adds the column up itself shows the row
    // sum; one that renders what the server sent shows the total. Every other
    // figure here comes from the backend, and this is a business value the
    // backend already owns (ADR 0020) — the base column is what each row's
    // status is judged on, so two computations of it can disagree in exactly
    // the place an operator is deciding whether payroll is right.
    server.use(http.get(ENDPOINT, () => HttpResponse.json(response([row()]))))

    renderWithProviders(<PayrollReconciliationPage weekStart={WEEK} />)

    expect(await screen.findByText('Charlie Nelson')).toBeVisible()
    expect(screen.getByText('$1,234.56')).toBeVisible()
  })

  it('calls out an employee Xero is paying that we posted nothing for', async () => {
    // Opus: The costliest error the reconciliation exists to find: Xero pays an
    // employee it holds on the calendar their pay-template hours when the run
    // carries no timesheet for them, and iterating our own staff list can
    // never surface it.
    server.use(
      http.get(ENDPOINT, () =>
        HttpResponse.json(
          response([
            row(),
            row({
              key: 'xero-emp-sam',
              name: 'Sam Patel',
              status: 'xero_only_departed',
              jm_hours: 0,
              jm_cost: 0,
              jm_base_pay: 0,
              xero_gross: 1600,
              pay_diff: -1600,
            }),
          ]),
        ),
      ),
    )

    renderWithProviders(<PayrollReconciliationPage weekStart={WEEK} />)

    expect(await screen.findByText('Left — Xero is still paying them')).toBeVisible()
    expect(
      document.querySelector('[data-automation-id="PayrollReconciliation-unposted-count"]')
        ?.textContent,
    ).toBe('1')
  })

  it('says so when Xero has no pay run, rather than reporting a difference', async () => {
    server.use(http.get(ENDPOINT, () => HttpResponse.json(response([], 'no_pay_run'))))

    renderWithProviders(<PayrollReconciliationPage weekStart={WEEK} />)

    expect(
      await screen.findByText(/Xero has no pay run for this week yet/, { exact: false }),
    ).toBeVisible()
  })
})
