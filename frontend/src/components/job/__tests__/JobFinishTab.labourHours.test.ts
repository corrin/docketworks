import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const { finishRetrieveMock, invoicesRetrieveMock, costsSummaryRetrieveMock } = vi.hoisted(() => ({
  finishRetrieveMock: vi.fn(),
  invoicesRetrieveMock: vi.fn(),
  costsSummaryRetrieveMock: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_finish_retrieve: finishRetrieveMock,
    job_jobs_invoices_retrieve: invoicesRetrieveMock,
    job_jobs_costs_summary_retrieve: costsSummaryRetrieveMock,
    job_jobs_finish_partial_update: vi.fn(),
    xero_create_invoice_create: vi.fn(),
    xero_delete_invoice_destroy: vi.fn(),
  },
}))

vi.mock('@/composables/useXeroConnection', () => ({
  useXeroConnection: () => ({ xeroConnected: { value: true } }),
}))

vi.mock('vue-sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

import JobFinishTab from '../JobFinishTab.vue'

/**
 * KAN-222: office staff read labour budget, hours used and hours remaining
 * without doing the subtraction, and an overrun shows as a positive number
 * rather than a negative remainder.
 */
const summary = () => ({
  basis: 'quote',
  job_value_excl_gst: 1000,
  valid_invoiced_excl_gst: 0,
  outstanding_invoiced_incl_gst: 0,
  remaining_to_invoice_excl_gst: 1000,
  remaining_gst: 150,
  remaining_to_invoice_incl_gst: 1150,
  total_to_pay_incl_gst: 1150,
  over_invoiced_excl_gst: 0,
})

const checklist = () => ({
  foreman_signed_off: false,
  timesheets_collected: false,
  materials_checked: false,
  customer_called: false,
  released: false,
})

let mounted: ReturnType<typeof mount> | null = null

function mountWithHours(
  {
    estimateHours,
    quoteHours,
    actualHours,
  }: { estimateHours: number; quoteHours: number; actualHours: number },
  pricingMethodology = 'fixed_price',
) {
  costsSummaryRetrieveMock.mockResolvedValue({
    estimate: { cost: 500, rev: 800, hours: estimateHours, profitMargin: 60 },
    quote: quoteHours > 0 ? { cost: 600, rev: 1000, hours: quoteHours, profitMargin: 66 } : null,
    actual: { cost: 550, rev: 900, hours: actualHours, profitMargin: 63 },
  })
  mounted = mount(JobFinishTab, {
    props: { jobId: 'job-1', pricingMethodology, jobStatus: 'in_progress' },
    attachTo: document.body,
  })
  return mounted
}

const hours = (wrapper: ReturnType<typeof mountWithHours>, which: string) =>
  wrapper.find(`[data-automation-id="JobFinishTab-labour-${which}"]`).text()

const remainingLabel = (wrapper: ReturnType<typeof mountWithHours>) =>
  wrapper.find('[data-automation-id="JobFinishTab-labour-hours"]').text()

describe('JobFinishTab labour hours', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    finishRetrieveMock.mockResolvedValue({ summary: summary(), checklist: checklist() })
    invoicesRetrieveMock.mockResolvedValue({ invoices: [] })
  })

  afterEach(() => {
    mounted?.unmount()
    mounted = null
    document.body.innerHTML = ''
  })

  it('shows budget, used and remaining for an under-budget job', async () => {
    const wrapper = mountWithHours({ estimateHours: 10, quoteHours: 12, actualHours: 8 })
    await flushPromises()

    expect(hours(wrapper, 'budget')).toBe('12')
    expect(hours(wrapper, 'used')).toBe('8')
    expect(hours(wrapper, 'remaining')).toBe('4')
    expect(remainingLabel(wrapper)).toContain('Hours remaining')
  })

  it('shows zero remaining and no overrun exactly on budget', async () => {
    const wrapper = mountWithHours({ estimateHours: 10, quoteHours: 12, actualHours: 12 })
    await flushPromises()

    expect(hours(wrapper, 'remaining')).toBe('0')
    expect(remainingLabel(wrapper)).toContain('Hours remaining')
    expect(remainingLabel(wrapper)).not.toContain('Overrun')
  })

  it('shows an overrun as a positive number, not a negative remainder', async () => {
    const wrapper = mountWithHours({ estimateHours: 10, quoteHours: 12, actualHours: 15 })
    await flushPromises()

    expect(hours(wrapper, 'remaining')).toBe('3')
    expect(remainingLabel(wrapper)).toContain('Overrun')
    expect(hours(wrapper, 'remaining')).not.toContain('-')
  })

  it('budgets a fixed-price job from its quote hours', async () => {
    const wrapper = mountWithHours({ estimateHours: 10, quoteHours: 12, actualHours: 5 })
    await flushPromises()

    expect(hours(wrapper, 'budget')).toBe('12')
  })

  it('budgets a fixed-price job with no quote from its estimate hours', async () => {
    const wrapper = mountWithHours({ estimateHours: 10, quoteHours: 0, actualHours: 5 })
    await flushPromises()

    expect(hours(wrapper, 'budget')).toBe('10')
  })

  it('budgets a T&M job from its estimate hours', async () => {
    const wrapper = mountWithHours(
      { estimateHours: 10, quoteHours: 12, actualHours: 5 },
      'time_materials',
    )
    await flushPromises()

    expect(hours(wrapper, 'budget')).toBe('10')
  })
})
