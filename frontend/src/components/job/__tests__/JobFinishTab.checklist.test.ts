import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'

const {
  finishRetrieveMock,
  invoicesRetrieveMock,
  costsSummaryRetrieveMock,
  checklistUpdateMock,
  toastErrorMock,
} = vi.hoisted(() => ({
  finishRetrieveMock: vi.fn(),
  invoicesRetrieveMock: vi.fn(),
  costsSummaryRetrieveMock: vi.fn(),
  checklistUpdateMock: vi.fn(),
  toastErrorMock: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_finish_retrieve: finishRetrieveMock,
    job_jobs_invoices_retrieve: invoicesRetrieveMock,
    job_jobs_costs_summary_retrieve: costsSummaryRetrieveMock,
    job_jobs_finish_partial_update: checklistUpdateMock,
    xero_create_invoice_create: vi.fn(),
    xero_delete_invoice_destroy: vi.fn(),
  },
}))

vi.mock('@/composables/useXeroConnection', () => ({
  useXeroConnection: () => ({ xeroConnected: { value: true } }),
}))

vi.mock('vue-sonner', () => ({
  toast: { error: toastErrorMock, success: vi.fn(), warning: vi.fn() },
}))

import JobFinishTab from '../JobFinishTab.vue'
import {
  CHECKLIST_ITEMS as ITEMS,
  checklistState as checklist,
  costSummary,
  finishSummary as summary,
  mountFinishTab,
  resetFinishTab,
} from './finishTabFixtures'

const mountTab = (pricingMethodology = 'fixed_price') =>
  mountFinishTab(JobFinishTab, pricingMethodology)

const item = (wrapper: ReturnType<typeof mountTab>, key: string) =>
  wrapper.find(`[data-automation-id="JobFinishTab-checklist-${key}"]`)

describe('JobFinishTab completion checklist', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    finishRetrieveMock.mockResolvedValue({ summary: summary(), checklist: checklist() })
    invoicesRetrieveMock.mockResolvedValue({ invoices: [] })
    costsSummaryRetrieveMock.mockResolvedValue(costSummary())
  })

  afterEach(resetFinishTab)

  it('asks all five questions on a T&M job', async () => {
    const wrapper = mountTab('time_materials')
    await flushPromises()

    for (const key of ITEMS) {
      expect(item(wrapper, key).exists(), key).toBe(true)
    }
  })

  it('does not ask about timesheets on a quoted job', async () => {
    const wrapper = mountTab('fixed_price')
    await flushPromises()

    expect(item(wrapper, 'timesheets_collected').exists()).toBe(false)
    for (const key of ITEMS.filter((k) => k !== 'timesheets_collected')) {
      expect(item(wrapper, key).exists(), key).toBe(true)
    }
  })

  it('reflects ticks already recorded on the job', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary(),
      checklist: checklist({ foreman_signed_off: true }),
    })
    const wrapper = mountTab()
    await flushPromises()

    expect((item(wrapper, 'foreman_signed_off').element as HTMLInputElement).checked).toBe(true)
    expect((item(wrapper, 'released').element as HTMLInputElement).checked).toBe(false)
  })

  it('sends only the item that changed', async () => {
    checklistUpdateMock.mockResolvedValue({
      summary: summary(),
      checklist: checklist({ materials_checked: true }),
    })
    const wrapper = mountTab()
    await flushPromises()

    await item(wrapper, 'materials_checked').setValue(true)
    await flushPromises()

    expect(checklistUpdateMock).toHaveBeenCalledWith(
      { materials_checked: true },
      { params: { job_id: 'job-1' } },
    )
  })

  it('sends false when a tick is withdrawn', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary(),
      checklist: checklist({ released: true }),
    })
    checklistUpdateMock.mockResolvedValue({ summary: summary(), checklist: checklist() })
    const wrapper = mountTab()
    await flushPromises()

    await item(wrapper, 'released').setValue(false)
    await flushPromises()

    expect(checklistUpdateMock).toHaveBeenCalledWith(
      { released: false },
      { params: { job_id: 'job-1' } },
    )
  })

  it('reverts the box and warns the user when the save fails', async () => {
    checklistUpdateMock.mockRejectedValue(new Error('nope'))
    const wrapper = mountTab()
    await flushPromises()

    await item(wrapper, 'foreman_signed_off').setValue(true)
    await flushPromises()

    expect(toastErrorMock).toHaveBeenCalledWith('Failed to save checklist')
    expect((item(wrapper, 'foreman_signed_off').element as HTMLInputElement).checked).toBe(false)
  })

  it('does not hide the invoice action behind the checklist', async () => {
    const wrapper = mountTab()
    await flushPromises()

    expect((item(wrapper, 'foreman_signed_off').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find('[data-automation-id="JobFinishTab-create-invoice"]').exists()).toBe(true)
  })
})
