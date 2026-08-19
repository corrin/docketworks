import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { WeeklyOverviewPage, weeklySearchFromUrl } from './WeeklyOverviewPage'

const WEEK = '2026-08-03'
const TUESDAY = '2026-08-04'

function day(date: string, overrides: Record<string, unknown> = {}) {
  return {
    day: date,
    hours: 0,
    billable_hours: 0,
    scheduled_hours: 8,
    day_status: 'No Entry',
    has_leave: false,
    billed_hours: 0,
    unbilled_hours: 0,
    overtime_1_5x_hours: 0,
    overtime_2x_hours: 0,
    sick_leave_hours: 0,
    annual_leave_hours: 0,
    bereavement_leave_hours: 0,
    other_leave_hours: 0,
    daily_cost: 0,
    daily_base_cost: 0,
    ...overrides,
  }
}

const MONDAY = '2026-08-03'
const WEDNESDAY = '2026-08-05'
const THURSDAY = '2026-08-06'
const FRIDAY = '2026-08-07'
const WEEK_DAYS = [MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY]

/** Query one element, failing the test rather than asserting it is non-null. */
function el(automationId: string): HTMLElement {
  const found = document.querySelector(`[data-automation-id="${automationId}"]`)
  if (!(found instanceof HTMLElement)) {
    throw new Error(`No element with data-automation-id="${automationId}"`)
  }
  return found
}

const weeklyPayload = {
  start_date: WEEK,
  end_date: '2026-08-07',
  week_days: WEEK_DAYS,
  staff_data: [
    {
      staff_id: '11111111-1111-1111-1111-111111111111',
      staff_name: 'Wendy Workshop',
      weekly_hours: [
        day(MONDAY, { hours: 8, billable_hours: 8, day_status: 'Complete', billed_hours: 8 }),
        day(TUESDAY, { hours: 4, billable_hours: 4, day_status: 'Partial', billed_hours: 4 }),
        day(WEDNESDAY),
        day(THURSDAY, { day_status: 'Leave', has_leave: true, sick_leave_hours: 8, hours: 8 }),
        day(FRIDAY),
      ],
      total_hours: 20,
      total_billable_hours: 12,
      total_scheduled_hours: 40,
      billable_percentage: 60,
      week_status: 'Partial',
      total_billed_hours: 12,
      total_unbilled_hours: 0,
      total_overtime_hours: 0,
      total_overtime_1_5x_hours: 0,
      total_overtime_2x_hours: 0,
      total_sick_leave_hours: 8,
      total_annual_leave_hours: 0,
      total_bereavement_leave_hours: 0,
      total_other_leave_hours: 0,
      weekly_cost: 960,
      weekly_base_cost: 800,
      pay_basis: 'hourly',
      expected_hours: 40,
      variance_hours: -20,
    },
  ],
  weekly_summary: { total_hours: 20, staff_count: 1, billable_percentage: 60 },
  job_metrics: { total_estimated_profit: 0, total_actual_profit: 0, total_profit: 0 },
  summary_stats: {
    total_staff: 1,
    complete_staff: 0,
    partial_staff: 1,
    missing_staff: 0,
    completion_rate: 0,
  },
  export_mode: 'payroll',
  is_current_week: false,
  navigation: {
    prev_week_date: '2026-07-27',
    next_week_date: '2026-08-10',
    current_week_date: WEEK,
  },
  weekend_enabled: false,
  week_type: '5-day',
}

const payRunsPayload = {
  pay_runs: [],
  next_postable_week_start_date: WEEK,
  next_postable_week_end_date: '2026-08-09',
}

/** Xero agreeing with the timesheet: the case the panel should stay quiet about. */
const inSyncStatus = {
  week_start_date: WEEK,
  staff: [
    {
      staff_id: '11111111-1111-1111-1111-111111111111',
      posted: true,
      timesheet_status: 'Approved',
      posted_timesheet_hours: 8,
      posted_leave_hours: 0,
      recorded_timesheet_hours: 8,
      recorded_leave_hours: 0,
      matches: true,
    },
  ],
}

function mockWeek(
  payRuns: Record<string, unknown> = payRunsPayload,
  weekStatus: Record<string, unknown> = inSyncStatus,
  weekly: Record<string, unknown> = weeklyPayload,
) {
  server.use(
    http.get('*/api/timesheets/weekly/', () => HttpResponse.json(weekly)),
    http.get('*/api/timesheets/payroll/pay-runs/', () => HttpResponse.json(payRuns)),
    http.get('*/api/timesheets/payroll/week-status/', () => HttpResponse.json(weekStatus)),
  )
}

function renderPage(overrides: Partial<Parameters<typeof WeeklyOverviewPage>[0]> = {}) {
  const props = {
    search: { week: WEEK },
    onWeekChange: vi.fn(),
    onOpenDay: vi.fn(),
    onOpenEntry: vi.fn(),
    ...overrides,
  }
  renderWithProviders(<WeeklyOverviewPage {...props} />)
  return props
}

describe('WeeklyOverviewPage', () => {
  it('renders a row per staff member with the week total', async () => {
    mockWeek()
    renderPage()

    await waitFor(() => {
      expect(
        document.querySelector(
          '[data-automation-id="WeeklyOverview-row-11111111-1111-1111-1111-111111111111"]',
        ),
      ).not.toBe(null)
    })
    expect(
      document.querySelector(
        '[data-automation-id="WeeklyOverview-total-11111111-1111-1111-1111-111111111111"]',
      )?.textContent,
    ).toBe('20h')
  })

  it('gently warns when salaried allocation differs from expected hours', async () => {
    const salaried = {
      ...weeklyPayload,
      staff_data: [
        {
          ...weeklyPayload.staff_data[0],
          pay_basis: 'salary',
          expected_hours: 40,
          variance_hours: -20,
        },
      ],
    }
    mockWeek(payRunsPayload, inSyncStatus, salaried)
    renderPage()

    await waitFor(() => expect(document.body).toHaveTextContent('20h unallocated'))
    expect(document.body).toHaveTextContent('salary unchanged')
  })

  it('shows the server total rather than recomputing it', async () => {
    mockWeek()
    renderPage()

    await waitFor(() => {
      expect(
        document.querySelector('[data-automation-id="WeeklyOverview-totalHours"]')?.textContent,
      ).toBe('20h')
    })
  })

  it('opens the daily overview from a day header', async () => {
    mockWeek()
    const props = renderPage()

    await waitFor(() => {
      expect(
        document.querySelector(`[data-automation-id="WeeklyOverview-dayHeader-${TUESDAY}"]`),
      ).not.toBe(null)
    })
    await userEvent.click(el(`WeeklyOverview-dayHeader-${TUESDAY}`))

    expect(props.onOpenDay).toHaveBeenCalledWith(TUESDAY)
  })

  it('opens one staff member’s entries from their cell', async () => {
    mockWeek()
    const props = renderPage()

    const selector = `[data-automation-id="WeeklyOverview-cell-11111111-1111-1111-1111-111111111111-${TUESDAY}"]`
    await waitFor(() => {
      expect(document.querySelector(selector)).not.toBe(null)
    })
    await userEvent.click(el(`WeeklyOverview-cell-11111111-1111-1111-1111-111111111111-${TUESDAY}`))

    expect(props.onOpenEntry).toHaveBeenCalledWith('11111111-1111-1111-1111-111111111111', TUESDAY)
  })

  it('expands a staff row into its payroll categories', async () => {
    mockWeek()
    renderPage()

    await waitFor(() => {
      expect(
        document.querySelector(
          '[data-automation-id="WeeklyOverview-expand-11111111-1111-1111-1111-111111111111"]',
        ),
      ).not.toBe(null)
    })
    await userEvent.click(el('WeeklyOverview-expand-11111111-1111-1111-1111-111111111111'))

    // Opus: Only the categories with hours appear; empty ones would be noise.
    expect(
      document.querySelector(
        '[data-automation-id="WeeklyOverview-breakdown-11111111-1111-1111-1111-111111111111-Billed"]',
      ),
    ).not.toBe(null)
    expect(
      document.querySelector(
        '[data-automation-id="WeeklyOverview-breakdown-11111111-1111-1111-1111-111111111111-Sick leave"]',
      ),
    ).not.toBe(null)
    expect(
      document.querySelector(
        '[data-automation-id="WeeklyOverview-breakdown-11111111-1111-1111-1111-111111111111-Annual leave"]',
      ),
    ).toBe(null)
  })

  it('offers Create Pay Run only when the week has none', async () => {
    mockWeek()
    renderPage()

    await waitFor(() => {
      expect(
        document.querySelector('[data-automation-id="PayrollPanel-status"]')?.textContent,
      ).toBe('Pay run not created yet')
    })
    expect(document.querySelector('[data-automation-id="PayrollPanel-createPayRun"]')).not.toBe(
      null,
    )
    // Opus: This asserted Post was DISABLED without a pay run. That was the
    // defect, not the contract: posting reconciles leave before creating the
    // pay run, because Xero locks leave once the employee is in a draft
    // (KAN-326), so requiring a draft first defeated the ordering on every
    // post. v1 never had the precondition — it offers one combined "Post to
    // Xero & Create Pay Run" action. Create Pay Run remains as a convenience;
    // it is no longer a gate.
    expect(
      document
        .querySelector('[data-automation-id="PayrollPanel-postAll"]')
        ?.hasAttribute('disabled'),
    ).toBe(false)
  })

  it('enables posting once a draft pay run exists', async () => {
    mockWeek({
      pay_runs: [
        {
          id: 'run-1',
          xero_id: 'xero-run-1',
          period_start_date: WEEK,
          period_end_date: '2026-08-09',
          payment_date: '2026-08-12',
          pay_run_status: 'Draft',
          xero_url: 'https://payroll.xero.com/PayRun',
        },
      ],
      next_postable_week_start_date: WEEK,
      next_postable_week_end_date: '2026-08-09',
    })
    renderPage()

    await waitFor(() => {
      expect(
        document.querySelector('[data-automation-id="PayrollPanel-status"]')?.textContent,
      ).toBe('Pay run ready for posting')
    })
    expect(
      document
        .querySelector('[data-automation-id="PayrollPanel-postAll"]')
        ?.hasAttribute('disabled'),
    ).toBe(false)
    expect(document.querySelector('[data-automation-id="PayrollPanel-createPayRun"]')).toBe(null)
  })

  it('refuses to post a week Xero has already locked', async () => {
    mockWeek({
      pay_runs: [
        {
          id: 'run-1',
          xero_id: 'xero-run-1',
          period_start_date: WEEK,
          period_end_date: '2026-08-09',
          payment_date: '2026-08-12',
          pay_run_status: 'Posted',
          xero_url: 'https://payroll.xero.com/PayRun',
        },
      ],
      next_postable_week_start_date: WEEK,
      next_postable_week_end_date: '2026-08-09',
    })
    renderPage()

    await waitFor(() => {
      expect(
        document.querySelector('[data-automation-id="PayrollPanel-status"]')?.textContent,
      ).toBe('Pay run locked (already paid)')
    })
    expect(
      document
        .querySelector('[data-automation-id="PayrollPanel-postAll"]')
        ?.hasAttribute('disabled'),
    ).toBe(true)
  })

  it('says which week is postable when this one is not', async () => {
    mockWeek({
      pay_runs: [],
      next_postable_week_start_date: '2026-07-27',
      next_postable_week_end_date: '2026-08-02',
    })
    renderPage()

    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="PayrollPanel-notPostable"]')).not.toBe(
        null,
      )
    })
    expect(document.querySelector('[data-automation-id="PayrollPanel-createPayRun"]')).toBe(null)
  })

  it('does not offer to create a pay run when the pay-run read failed', async () => {
    server.use(
      http.get('*/api/timesheets/weekly/', () => HttpResponse.json(weeklyPayload)),
      http.get('*/api/timesheets/payroll/pay-runs/', () => new HttpResponse(null, { status: 500 })),
      http.get('*/api/timesheets/payroll/week-status/', () => HttpResponse.json(inSyncStatus)),
    )
    renderPage()

    await waitFor(() => {
      expect(document.body.textContent).toContain('Could not load pay runs from Xero')
    })
    expect(document.querySelector('[data-automation-id="PayrollPanel-createPayRun"]')).toBe(null)
  })
})

describe('WeeklyOverviewPage — what Xero holds', () => {
  /** Click "Check against Xero" — the read is deliberately not automatic. */
  async function checkXero() {
    await waitFor(() => el('PayrollPanel-checkXero'))
    await userEvent.click(el('PayrollPanel-checkXero'))
  }

  it('does not ask Xero until told to', async () => {
    // Opus: The read costs one Xero API call per staff member, paced at one in
    // flight with a 1s gap. Spending that on every visit to the grid, to
    // answer a question nobody asked, is what this guards.
    let asked = 0
    server.use(
      http.get('*/api/timesheets/weekly/', () => HttpResponse.json(weeklyPayload)),
      http.get('*/api/timesheets/payroll/pay-runs/', () => HttpResponse.json(payRunsPayload)),
      http.get('*/api/timesheets/payroll/week-status/', () => {
        asked += 1
        return HttpResponse.json(inSyncStatus)
      }),
    )
    renderPage()

    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="PayrollPanel-checkXero"]')).not.toBe(null)
    })
    expect(asked).toBe(0)
    expect(document.querySelector('[data-automation-id="PayrollPanel-inSync"]')).toBe(null)
  })

  it('says so plainly when Xero agrees with the timesheet', async () => {
    mockWeek()
    renderPage()
    await checkXero()

    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="PayrollPanel-inSync"]')).not.toBe(null)
    })
    expect(document.querySelector('[data-automation-id="PayrollPanel-outOfSync"]')).toBe(null)
  })

  it('names both surfaces when Xero disagrees', async () => {
    // Opus: Hours edited after a post: the screen looks posted and Xero is behind.
    // Reported per surface because only leave debits a leave balance, so the
    // same shortfall means something different on each.
    mockWeek(payRunsPayload, {
      week_start_date: WEEK,
      staff: [
        {
          staff_id: '11111111-1111-1111-1111-111111111111',
          posted: true,
          timesheet_status: 'Approved',
          posted_timesheet_hours: 8,
          posted_leave_hours: 0,
          recorded_timesheet_hours: 9.5,
          recorded_leave_hours: 0,
          matches: false,
        },
      ],
    })
    renderPage()
    await checkXero()

    await waitFor(() => {
      expect(
        document.querySelector(
          '[data-automation-id="PayrollPanel-outOfSync-11111111-1111-1111-1111-111111111111"]',
        ),
      ).not.toBe(null)
    })
    const text = document.querySelector(
      '[data-automation-id="PayrollPanel-outOfSync-11111111-1111-1111-1111-111111111111"]',
    )?.textContent
    expect(text).toContain('8h worked')
    expect(text).toContain('9.5h worked')
    expect(document.querySelector('[data-automation-id="PayrollPanel-inSync"]')).toBe(null)
  })

  it('warns rather than implying the hours are posted when Xero cannot be read', async () => {
    // Opus: The dangerous failure: showing recorded hours with no caveat reads as
    // confirmation that Xero holds them.
    server.use(
      http.get('*/api/timesheets/weekly/', () => HttpResponse.json(weeklyPayload)),
      http.get('*/api/timesheets/payroll/pay-runs/', () => HttpResponse.json(payRunsPayload)),
      http.get(
        '*/api/timesheets/payroll/week-status/',
        () => new HttpResponse(null, { status: 500 }),
      ),
    )
    renderPage()
    await checkXero()

    await waitFor(() => {
      expect(
        document.querySelector('[data-automation-id="PayrollPanel-statusUnavailable"]'),
      ).not.toBe(null)
    })
    expect(document.querySelector('[data-automation-id="PayrollPanel-inSync"]')).toBe(null)
  })
})

describe('WeeklyOverviewPage — before the pay-run read resolves', () => {
  it('offers no pay-run creation while the read is still in flight', async () => {
    // Opus: While loading, `payRun` is undefined so the state reads "missing" and
    // `postableWeekStart` is null so every week reads as postable. Together
    // those rendered an ENABLED Create button that could race the read and try
    // to create a run for a week that already has one.
    server.use(
      http.get('*/api/timesheets/weekly/', () => HttpResponse.json(weeklyPayload)),
      http.get('*/api/timesheets/payroll/pay-runs/', async () => {
        await delay(200)
        return HttpResponse.json(payRunsPayload)
      }),
      http.get('*/api/timesheets/payroll/week-status/', () => HttpResponse.json(inSyncStatus)),
    )
    renderPage()

    await waitFor(() => {
      expect(
        document.querySelector('[data-automation-id="PayrollPanel-status"]')?.textContent,
      ).toContain('Reading pay runs')
    })
    expect(document.querySelector('[data-automation-id="PayrollPanel-createPayRun"]')).toBe(null)
    expect(
      document
        .querySelector('[data-automation-id="PayrollPanel-postAll"]')
        ?.hasAttribute('disabled'),
    ).toBe(true)

    // Opus: And once it lands, the offer appears on its own.
    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="PayrollPanel-createPayRun"]')).not.toBe(
        null,
      )
    })
  })

  it('falls back to the current week when the server cannot name a postable one', async () => {
    // Opus: A loaded null is the server saying it could not ask Xero. Its documented
    // contract is the current week — it used to authorise EVERY week, so any
    // week the operator happened to open offered to create a pay run.
    mockWeek({
      pay_runs: [],
      next_postable_week_start_date: null,
      next_postable_week_end_date: null,
    })
    renderPage()

    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="PayrollPanel-notPostable"]')).not.toBe(
        null,
      )
    })
    // Opus: WEEK is 2026-08-03, not the current week, so it must not be offered.
    expect(document.querySelector('[data-automation-id="PayrollPanel-createPayRun"]')).toBe(null)
  })
})

describe('weeklySearchFromUrl', () => {
  it('snaps a mid-week value to its Monday', () => {
    // Opus: 2026-08-04 is a Tuesday. Left as-is it ran the grid, the displayed range
    // and the payroll panel off a Tuesday — a week the server can never accept,
    // since `_WeekWindow.of` refuses a non-Monday.
    expect(weeklySearchFromUrl({ week: '2026-08-04' })).toEqual({ week: '2026-08-03' })
  })

  it('leaves a Monday alone', () => {
    expect(weeklySearchFromUrl({ week: '2026-08-03' })).toEqual({ week: '2026-08-03' })
  })

  it('treats a Sunday as the week it ends, not the one it precedes', () => {
    expect(weeklySearchFromUrl({ week: '2026-08-09' })).toEqual({ week: '2026-08-03' })
  })

  it('ignores anything that is not an ISO date', () => {
    expect(weeklySearchFromUrl({ week: 'last-week' })).toEqual({ week: undefined })
    expect(weeklySearchFromUrl({})).toEqual({ week: undefined })
  })
})
