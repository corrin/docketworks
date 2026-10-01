import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import type {
  KpiCalendarResponse,
  KpiDayDataOut,
  KpiJobBreakdownOut,
  KpiMonthlyTotalsOut,
} from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'

import { KpiCalendarPage } from './KpiCalendarPage'
import type { KpiSearch } from './kpiSearch'

const CALENDAR_URL = '*/api/accounting/reports/calendar/'

// Typed against the generated wire types: an untyped literal stays green
// through a backend field rename that breaks the page.
const JOB_ID = '73933669-5f44-413c-962c-3954f948492f'

function job(overrides: Partial<KpiJobBreakdownOut> = {}): KpiJobBreakdownOut {
  return {
    job_id: JOB_ID,
    job_number: '97176',
    job_name: 'CUT WATER TANK',
    company_name: 'Miller-Mcpherson',
    billable_hours: 4,
    revenue: 500,
    cost: 100,
    profit: 400,
    labour_profit: 123,
    material_profit: 250,
    adjustment_profit: 27,
    ...overrides,
  }
}

/**
 * A weekday whose served profit breakdown deliberately DISAGREES with revenue
 * less cost (500 - 100 = 400, served 123): a cell that subtracts for itself
 * shows $400 and fails the breakdown test.
 */
function day(date: string, overrides: Partial<KpiDayDataOut> = {}): KpiDayDataOut {
  return {
    date,
    day: Number(date.slice(8)),
    holiday: false,
    holiday_name: null,
    billable_hours: 6,
    total_hours: 8,
    shop_hours: 2,
    shop_percentage: 25,
    gross_profit: 400,
    color_hours: 'green',
    color_gp: 'red',
    gp_target_achievement: 40,
    details: {
      time_revenue: 500,
      material_revenue: 300,
      adjustment_revenue: 30,
      total_revenue: 830,
      staff_cost: 100,
      material_cost: 50,
      adjustment_cost: 3,
      total_cost: 153,
      profit_breakdown: { labour_profit: 123, material_profit: 250, adjustment_profit: 27 },
      job_breakdown: [job()],
    },
    ...overrides,
  }
}

/**
 * Totals that disagree with any sum of the days above: the cards must show
 * these, and a card that re-summed the calendar would show something else.
 */
function totals(overrides: Partial<KpiMonthlyTotalsOut> = {}): KpiMonthlyTotalsOut {
  return {
    billable_hours: 99,
    total_hours: 120,
    shop_hours: 10,
    gross_profit: 9999,
    days_green: 1,
    days_amber: 0,
    days_red: 21,
    labour_green_days: 1,
    labour_amber_days: 0,
    labour_red_days: 21,
    profit_green_days: 0,
    profit_amber_days: 0,
    profit_red_days: 22,
    working_days: 22,
    elapsed_workdays: 22,
    weekdays: 22,
    elapsed_weekdays: 22,
    active_days: 2,
    remaining_workdays: 0,
    remaining_weekdays: 0,
    time_revenue: 5000,
    material_revenue: 3000,
    adjustment_revenue: 300,
    staff_cost: 1000,
    material_cost: 500,
    adjustment_cost: 30,
    labour_profit: 4000,
    material_profit: 2500,
    adjustment_profit: 270,
    total_revenue: 8300,
    total_cost: 1530,
    elapsed_target: 22000,
    net_profit: -12001,
    billable_percentage: 82.5,
    shop_percentage: 8.3,
    avg_weekday_gp: 454.5,
    avg_active_day_gp: 4999.5,
    avg_active_day_billable_hours: 49.5,
    gross_margin: 81.6,
    net_margin: -144.6,
    labour_margin: 80,
    material_margin: 83.3,
    adjustment_margin: null,
    avg_labour_rate: 50.51,
    labour_revenue_share: 60.2,
    month_target: 22000,
    month_target_achievement: 45.5,
    color_hours: 'green',
    color_gp: 'red',
    color_shop: 'green',
    ...overrides,
  }
}

/** June 2026 starts on a Monday; the 1st is King's Birthday. */
function june(overrides: Partial<KpiCalendarResponse> = {}): KpiCalendarResponse {
  return {
    year: 2026,
    month: 6,
    weekend_enabled: false,
    thresholds: {
      kpi_daily_billable_hours_green: 8,
      kpi_daily_billable_hours_amber: 5,
      kpi_daily_gp_target: 1000,
      kpi_daily_shop_hours_percentage: 20,
      kpi_daily_gp_green: 500,
      kpi_daily_gp_amber: 250,
    },
    calendar_data: {
      '2026-06-01': day('2026-06-01', { holiday: true, holiday_name: "King's Birthday" }),
      '2026-06-03': day('2026-06-03'),
    },
    monthly_totals: totals(),
    ...overrides,
  }
}

const juneWithWeekends = june({
  weekend_enabled: true,
  calendar_data: {
    '2026-06-03': day('2026-06-03'),
    '2026-06-06': day('2026-06-06', {
      color_hours: 'weekend',
      color_gp: 'weekend',
      gp_target_achievement: null,
    }),
  },
})

function serveCalendar(response: KpiCalendarResponse = june()): string[] {
  const requests: string[] = []
  server.use(
    http.get(CALENDAR_URL, ({ request }) => {
      requests.push(new URL(request.url).search)
      return HttpResponse.json(response)
    }),
  )
  return requests
}

/** The route's job, in miniature: hold the URL settings and apply a change. */
function Harness(initial: Partial<Required<KpiSearch>>) {
  const [search, setSearch] = useState<Required<KpiSearch>>({
    month: '2026-06',
    target: 'hours',
    decimals: 0,
    ...initial,
  })
  return (
    <>
      <KpiCalendarPage
        {...search}
        onSearchChange={(next) => setSearch((prev) => ({ ...prev, ...next }))}
      />
      {/* The browser's back button, in miniature: the month changes without
          the page's own nav, which a modal dialog puts out of reach. */}
      <button
        type="button"
        data-automation-id="Harness-back-a-month"
        onClick={() => setSearch((prev) => ({ ...prev, month: '2026-05' }))}
      >
        back
      </button>
    </>
  )
}

async function renderJune(initial: Partial<Required<KpiSearch>> = {}) {
  const rendered = renderWithProviders(<Harness {...initial} />)
  await screen.findByText('KPI Calendar')
  await waitFor(() => expect(queryAutoId('KpiCalendarReport-loading')).toBeNull())
  return rendered
}

describe('KpiCalendarPage', () => {
  it('reads the cards from monthly_totals, never by summing the days', async () => {
    serveCalendar()
    await renderJune()

    // 99h billed is nowhere in the two days served (6h each).
    expect(autoId('KpiCalendarReport-card-labour-value')).toHaveTextContent('99h billed')
    expect(autoId('KpiCalendarReport-card-material-value')).toHaveTextContent('$2,500')
    expect(autoId('KpiCalendarReport-card-adjustment-value')).toHaveTextContent('$270')
    // A null margin is a blank, not 0%: no adjustment revenue means no margin.
    expect(autoId('KpiCalendarReport-card-adjustment-value')).toHaveTextContent('— margin')
    expect(autoId('KpiCalendarReport-card-profit-value')).toHaveTextContent('-$12,001')
    // Whole dollars by default, across the whole report.
    expect(autoId('KpiCalendarReport-card-profit-value')).not.toHaveTextContent('.00')
  })

  it('shows the served profit breakdown in a cell, not revenue less cost', async () => {
    serveCalendar()
    await renderJune()

    const cell = autoId('KpiCalendarReport-day-2026-06-03')
    expect(cell).toHaveTextContent('$123')
    expect(cell).not.toHaveTextContent('$400 labour')
    expect(autoId('KpiCalendarReport-day-2026-06-03-gp')).toHaveTextContent('$400')
    // A holiday shows its gross profit and nothing else.
    const holiday = autoId('KpiCalendarReport-day-2026-06-01')
    expect(holiday).toHaveTextContent("King's Birthday")
    expect(holiday).not.toHaveTextContent('billable')
  })

  it('tints by the chosen ladder and leaves a weekend ungraded', async () => {
    serveCalendar(juneWithWeekends)
    const { user } = await renderJune()

    expect(autoId('KpiCalendarReport-day-2026-06-03')).toHaveAttribute('data-category', 'green')
    expect(autoId('KpiCalendarReport-day-2026-06-06')).toHaveAttribute('data-category', 'weekend')

    await user.click(autoId('KpiCalendarReport-target-dollars'))
    expect(autoId('KpiCalendarReport-day-2026-06-03')).toHaveAttribute('data-category', 'red')
    expect(autoId('KpiCalendarReport-day-2026-06-06')).toHaveAttribute('data-category', 'weekend')
    // The month's grade on the Labour card follows the same switch.
    expect(autoId('KpiCalendarReport-card-labour-grade')).toHaveTextContent('Behind')
  })

  it('places each day in its own weekday column, five or seven wide', async () => {
    serveCalendar(juneWithWeekends)
    await renderJune()

    expect(autoId('KpiCalendarReport-grid')).toHaveAttribute('data-columns', '7')
    // Wednesday the 3rd sits in column 3 and Saturday the 6th in column 6,
    // whatever came before them: a missing day never shifts a later one.
    expect(autoId('KpiCalendarReport-day-2026-06-03')).toHaveStyle({ gridColumnStart: '3' })
    expect(autoId('KpiCalendarReport-day-2026-06-06')).toHaveStyle({ gridColumnStart: '6' })
  })

  it('draws five columns when the weekend flag is off', async () => {
    serveCalendar()
    await renderJune()

    expect(autoId('KpiCalendarReport-grid')).toHaveAttribute('data-columns', '5')
    expect(screen.queryByText('Sat')).toBeNull()
  })

  it('fires exactly one request per month change', async () => {
    const requests = serveCalendar()
    const { user } = await renderJune()
    expect(requests).toEqual(['?year=2026&month=6'])

    await user.click(autoId('KpiCalendarReport-prev'))
    await waitFor(() => expect(requests).toHaveLength(2))
    // v1 fired two per change — the new year with the old month, then the
    // right one — and showed whichever answered last.
    expect(requests[1]).toBe('?year=2026&month=5')
    expect(autoId('KpiCalendarReport-month-label')).toHaveTextContent('May 2026')
  })

  it('opens the adjustments breakdown from the Adjustments card', async () => {
    serveCalendar()
    const { user } = await renderJune()

    await user.click(autoId('KpiCalendarReport-card-adjustment-breakdown'))

    // v1 wired this card to the Materials modal.
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAttribute('data-automation-id', 'KpiStreamDialog-adjustment-container')
    expect(within(dialog).getByRole('heading', { name: /^Adjustments — / })).toBeVisible()
    expect(autoId('KpiStreamDialog-adjustment-profit')).toHaveTextContent('$270')
  })

  it('opens a day and links each job through to the job page', async () => {
    serveCalendar()
    const { user } = await renderJune()

    await user.click(autoId('KpiCalendarReport-day-2026-06-03'))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAttribute('data-automation-id', 'KpiDayDetailsDialog-container')
    // The cell and the dialog render one figure through one formatter.
    expect(autoId('KpiDayDetailsDialog-gross-profit')).toHaveTextContent(
      autoId('KpiCalendarReport-day-2026-06-03-gp').textContent ?? '',
    )
    expect(autoId(`KpiDayDetailsDialog-job-${JOB_ID}`)).toHaveAttribute('href', `/jobs/${JOB_ID}`)
  })

  it('closes a breakdown when the month changes under it', async () => {
    serveCalendar()
    const { user } = await renderJune()

    await user.click(autoId('KpiCalendarReport-card-labour-breakdown'))
    await screen.findByRole('dialog')

    // The browser's back button or a pasted URL changes the month without
    // touching the page's nav (which the modal dialog covers anyway); it
    // arrives as a new `month` prop. A dialog that stayed open would retitle
    // itself with the next month's figures. fireEvent, because the open
    // dialog makes everything behind it pointer-events: none, as a real
    // browser would — and a back button is not behind it.
    fireEvent.click(autoId('Harness-back-a-month'))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(autoId('KpiCalendarReport-month-label')).toHaveTextContent('May 2026')
  })

  it('shows cents everywhere once asked', async () => {
    serveCalendar()
    const { user } = await renderJune()

    await user.click(autoId('KpiCalendarReport-decimals-2'))

    expect(autoId('KpiCalendarReport-card-material-value')).toHaveTextContent('$2,500.00')
    expect(autoId('KpiCalendarReport-day-2026-06-03-gp')).toHaveTextContent('$400.00')
  })

  it('reports failure with a retry instead of an empty calendar', async () => {
    let attempts = 0
    server.use(
      http.get(CALENDAR_URL, () => {
        attempts += 1
        return attempts === 1
          ? HttpResponse.json({ detail: 'unavailable' }, { status: 503 })
          : HttpResponse.json(june())
      }),
    )
    const { user } = renderWithProviders(<Harness />)

    expect(await screen.findByText('Failed to load the KPI calendar.')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(queryAutoId('KpiCalendarReport-grid')).not.toBeNull())
  })
})
