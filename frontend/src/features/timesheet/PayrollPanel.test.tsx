import { waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'

import { PayrollPanel } from './PayrollPanel'

import type { UsePayrollWeekResult } from './usePayrollWeek'

const WEEK = '2026-07-13'

/**
 * A payroll hook result with nothing in flight and nothing loaded.
 *
 * Opus: The panel takes the whole hook result, so a partial object would need a
 * cast — and a cast here would let a field this component reads go missing
 * without the type checker noticing, which is the class of defect the panel's
 * three-state postable logic exists to prevent.
 */
function payrollResult(overrides: Partial<UsePayrollWeekResult> = {}): UsePayrollWeekResult {
  return {
    payRun: undefined,
    payRunState: 'missing',
    postableWeekStart: WEEK,
    isLoading: false,
    loadFailed: false,
    createPayRun: vi.fn(),
    isCreating: false,
    refreshPayRuns: vi.fn(),
    isRefreshing: false,
    postWeek: vi.fn(),
    isPosting: false,
    progress: null,
    results: [],
    hasPosted: false,
    postingStatus: undefined,
    postingStatusFailed: false,
    isCheckingXero: false,
    checkXero: vi.fn(),
    ...overrides,
  }
}

/** The router resolves after render returns, so this waits rather than querying once. */
async function postButton(container: HTMLElement): Promise<HTMLButtonElement> {
  return await waitFor(() => {
    const button = container.querySelector<HTMLButtonElement>(
      '[data-automation-id="PayrollPanel-postAll"]',
    )
    if (button === null) throw new Error('Post button not rendered')
    return button
  })
}

describe('PayrollPanel — when posting is offered', () => {
  it('offers posting on the postable week even with no pay run yet', async () => {
    // Opus: The defect this pins. Requiring a draft first forced the operator to
    // create one, and posting reconciles leave BEFORE creating the pay run
    // because Xero locks leave once the employee is in a draft (KAN-326). So
    // the precondition defeated the ordering on every post, and deadlocked:
    // the resulting error says to delete the draft, which disabled the only
    // button that could recover.
    const { container } = renderWithProviders(
      <PayrollPanel weekStart={WEEK} payroll={payrollResult()} staffIds={['staff-1']} />,
    )

    expect((await postButton(container)).disabled).toBe(false)
    expect((await postButton(container)).title).toContain('creating the pay run')
  })

  it('offers posting when the week already has a draft pay run', async () => {
    const { container } = renderWithProviders(
      <PayrollPanel
        weekStart={WEEK}
        payroll={payrollResult({ payRunState: 'draft' })}
        staffIds={['staff-1']}
      />,
    )

    expect((await postButton(container)).disabled).toBe(false)
  })

  it('refuses a week Xero has already paid', async () => {
    const { container } = renderWithProviders(
      <PayrollPanel
        weekStart={WEEK}
        payroll={payrollResult({ payRunState: 'posted' })}
        staffIds={['staff-1']}
      />,
    )

    expect((await postButton(container)).disabled).toBe(true)
    expect((await postButton(container)).title).toBe('This week is locked')
  })

  it('refuses a week that is not the one Xero will take next', async () => {
    // Opus: Xero processes pay runs in order, so posting out of sequence is not
    // merely rejected — it would post to whichever period Xero has open.
    const { container } = renderWithProviders(
      <PayrollPanel weekStart="2026-06-01" payroll={payrollResult()} staffIds={['staff-1']} />,
    )

    expect((await postButton(container)).disabled).toBe(true)
    expect((await postButton(container)).title).toBe('This is not the next postable week')
  })

  it('refuses to post while the pay-run read is still in flight', async () => {
    // Opus: Until the read resolves, `payRunState` reads "missing" and
    // `postableWeekStart` is null — which together would otherwise render an
    // enabled button that races the read.
    const { container } = renderWithProviders(
      <PayrollPanel
        weekStart={WEEK}
        payroll={payrollResult({ isLoading: true, postableWeekStart: null })}
        staffIds={['staff-1']}
      />,
    )

    expect((await postButton(container)).disabled).toBe(true)
  })
})
