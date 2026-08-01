import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'

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
import {
  checklistState,
  costSummary,
  finishSummary,
  mountFinishTab,
  resetFinishTab,
} from './finishTabFixtures'

/**
 * KAN-222: office staff read budget, used and remaining without doing the
 * subtraction, and an overrun shows as a positive number rather than a negative
 * remainder.
 */
async function mountWithHours(
  hours: { estimate: number; quote: number; actual: number },
  pricingMethodology = 'fixed_price',
) {
  costsSummaryRetrieveMock.mockResolvedValue(costSummary(hours))
  const wrapper = mountFinishTab(JobFinishTab, pricingMethodology)
  await flushPromises()
  return wrapper
}

const tile = (wrapper: ReturnType<typeof mountFinishTab>, which: string) =>
  wrapper.find(`[data-automation-id="JobFinishTab-labour-${which}"]`).text()

describe('JobFinishTab labour hours', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    finishRetrieveMock.mockResolvedValue({
      summary: finishSummary(),
      checklist: checklistState(),
    })
    invoicesRetrieveMock.mockResolvedValue({ invoices: [] })
  })

  afterEach(resetFinishTab)

  it('reports budget, used and remaining-or-overrun', async () => {
    const cases = [
      { label: 'under budget', actual: 8, remaining: '4', heading: 'Hours remaining' },
      { label: 'exactly on budget', actual: 12, remaining: '0', heading: 'Hours remaining' },
      { label: 'over budget', actual: 15, remaining: '3', heading: 'Overrun' },
    ]

    for (const { label, actual, remaining, heading } of cases) {
      const wrapper = await mountWithHours({ estimate: 10, quote: 12, actual })

      expect(tile(wrapper, 'budget'), label).toBe('12')
      expect(tile(wrapper, 'used'), label).toBe(String(actual))
      expect(tile(wrapper, 'remaining'), label).toBe(remaining)
      expect(tile(wrapper, 'remaining'), label).not.toContain('-')
      expect(
        wrapper.find('[data-automation-id="JobFinishTab-labour-hours"]').text(),
        label,
      ).toContain(heading)

      resetFinishTab()
    }
  })

  it('budgets from quote hours, falling back to estimate hours', async () => {
    const cases = [
      { label: 'fixed price with a quote', quote: 12, methodology: 'fixed_price', budget: '12' },
      { label: 'fixed price, no quote', quote: 0, methodology: 'fixed_price', budget: '10' },
      { label: 'time and materials', quote: 12, methodology: 'time_materials', budget: '10' },
    ]

    for (const { label, quote, methodology, budget } of cases) {
      const wrapper = await mountWithHours({ estimate: 10, quote, actual: 5 }, methodology)

      expect(tile(wrapper, 'budget'), label).toBe(budget)

      resetFinishTab()
    }
  })
})
