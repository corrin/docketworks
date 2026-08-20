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
 * without the type checker noticing.
 */
function payrollResult(overrides: Partial<UsePayrollWeekResult> = {}): UsePayrollWeekResult {
  return {
    payRun: undefined,
    payRunState: 'missing',
    postableWeekStart: WEEK,
    isLoading: false,
    loadFailed: false,
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

function renderPanel(
  payroll: UsePayrollWeekResult,
  { weekStart = WEEK, onSelectWeek = vi.fn() } = {},
) {
  return {
    onSelectWeek,
    ...renderWithProviders(
      <PayrollPanel weekStart={weekStart} payroll={payroll} onSelectWeek={onSelectWeek} />,
    ),
  }
}

/** The router resolves after render returns, so this waits rather than querying once. */
async function autoId(container: HTMLElement, id: string): Promise<HTMLElement> {
  return await waitFor(() => {
    const element = container.querySelector<HTMLElement>(`[data-automation-id="${id}"]`)
    if (element === null) throw new Error(`${id} not rendered`)
    return element
  })
}

async function postButton(container: HTMLElement): Promise<HTMLButtonElement> {
  const element = await autoId(container, 'PayrollPanel-postAll')
  if (!(element instanceof HTMLButtonElement)) throw new Error('Post control is not a button')
  return element
}

describe('PayrollPanel — when posting is offered', () => {
  it('offers posting on the postable week even with no pay run yet', async () => {
    // Opus: The defect this pins. Requiring a draft first forced the operator to
    // create one, and posting reconciles leave BEFORE creating the pay run
    // because Xero locks leave once the employee is in a draft (KAN-326). So
    // the precondition defeated the ordering on every post, and deadlocked:
    // the resulting error says to delete the draft, which disabled the only
    // button that could recover.
    const { container } = renderPanel(payrollResult())

    expect((await postButton(container)).disabled).toBe(false)
    expect((await postButton(container)).title).toContain('creating the pay run')
  })

  it('offers posting when the week already has a draft pay run', async () => {
    const { container } = renderPanel(payrollResult({ payRunState: 'draft' }))

    expect((await postButton(container)).disabled).toBe(false)
  })

  it('refuses a week Xero has already paid', async () => {
    const { container } = renderPanel(payrollResult({ payRunState: 'posted' }))

    expect((await postButton(container)).disabled).toBe(true)
    expect((await postButton(container)).title).toBe('This week is locked')
  })

  it('still offers posting off the postable week, with the banner naming the right one', async () => {
    // Fable: The banner reads the mirror, which can be an hour stale, so it
    // advises rather than disables — the server enforces the same rule on a
    // mirror it refreshes inside the POST, and a stale read must never lock
    // the truly-postable week behind a disabled button with no recovery.
    const onSelectWeek = vi.fn()
    const { container } = renderPanel(payrollResult(), {
      weekStart: '2026-06-01',
      onSelectWeek,
    })

    expect((await postButton(container)).disabled).toBe(false)
    const banner = await autoId(container, 'PayrollPanel-notPostable')
    expect(banner.textContent).toContain('will be refused')

    const goTo = await autoId(container, 'PayrollPanel-goToPostableWeek')
    goTo.click()
    expect(onSelectWeek).toHaveBeenCalledWith(WEEK)
  })

  it('shows no banner on the postable week itself', async () => {
    const { container } = renderPanel(payrollResult())

    await postButton(container)
    expect(container.querySelector('[data-automation-id="PayrollPanel-notPostable"]')).toBeNull()
  })

  it('refuses to post while the pay-run read is still in flight', async () => {
    // Opus: Until the read resolves, `payRunState` reads "missing" — an enabled
    // button would race the read.
    const { container } = renderPanel(payrollResult({ isLoading: true, postableWeekStart: null }))

    expect((await postButton(container)).disabled).toBe(true)
  })

  it('posting names only the week — the roster is the server’s', async () => {
    const postWeek = vi.fn()
    const { container } = renderPanel(payrollResult({ postWeek }))

    ;(await postButton(container)).click()

    expect(postWeek).toHaveBeenCalledWith()
  })
})
