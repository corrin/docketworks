import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

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

const checklist = (overrides: Record<string, boolean | string | null> = {}) => ({
  time_entries_complete: false,
  materials_complete: false,
  customer_approval_confirmed: false,
  updated_at: null,
  updated_by_name: null,
  ...overrides,
})

let mounted: ReturnType<typeof mount> | null = null

function mountTab(pricingMethodology: string) {
  mounted = mount(JobFinishTab, {
    props: { jobId: 'job-1', pricingMethodology, jobStatus: 'in_progress' },
    attachTo: document.body,
  })
  return mounted
}

const item = (wrapper: ReturnType<typeof mountTab>, key: string) =>
  wrapper.find(`[data-automation-id="JobFinishTab-checklist-${key}"]`)

describe('JobFinishTab completion checklist', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    finishRetrieveMock.mockResolvedValue({ summary: summary(), checklist: checklist() })
    invoicesRetrieveMock.mockResolvedValue({ invoices: [] })
    costsSummaryRetrieveMock.mockResolvedValue({
      estimate: { cost: 500, rev: 800, hours: 10, profitMargin: 60 },
      quote: { cost: 600, rev: 1000, hours: 12, profitMargin: 66 },
      actual: { cost: 550, rev: 900, hours: 11, profitMargin: 63 },
    })
  })

  afterEach(() => {
    mounted?.unmount()
    mounted = null
    document.body.innerHTML = ''
  })

  it('asks a T&M job to confirm time, materials and customer approval', async () => {
    const wrapper = mountTab('time_materials')
    await flushPromises()

    expect(item(wrapper, 'time_entries_complete').exists()).toBe(true)
    expect(item(wrapper, 'materials_complete').exists()).toBe(true)
    expect(item(wrapper, 'customer_approval_confirmed').exists()).toBe(true)
  })

  it('asks a fixed-price job only for customer approval, and shows the quote basis', async () => {
    const wrapper = mountTab('fixed_price')
    await flushPromises()

    expect(item(wrapper, 'time_entries_complete').exists()).toBe(false)
    expect(item(wrapper, 'materials_complete').exists()).toBe(false)
    expect(item(wrapper, 'customer_approval_confirmed').exists()).toBe(true)
    expect(wrapper.find('[data-automation-id="JobFinishTab-quote-basis"]').text()).toContain(
      '1,000',
    )
  })

  it('reflects confirmations already recorded on the job', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary(),
      checklist: checklist({ materials_complete: true }),
    })
    const wrapper = mountTab('time_materials')
    await flushPromises()

    expect((item(wrapper, 'materials_complete').element as HTMLInputElement).checked).toBe(true)
    expect((item(wrapper, 'time_entries_complete').element as HTMLInputElement).checked).toBe(false)
  })

  it('sends only the item that changed', async () => {
    checklistUpdateMock.mockResolvedValue({
      summary: summary(),
      checklist: checklist({ materials_complete: true }),
    })
    const wrapper = mountTab('time_materials')
    await flushPromises()

    await item(wrapper, 'materials_complete').setValue(true)
    await flushPromises()

    expect(checklistUpdateMock).toHaveBeenCalledWith(
      { materials_complete: true },
      { params: { job_id: 'job-1' } },
    )
  })

  it('sends false when a confirmation is withdrawn', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary(),
      checklist: checklist({ materials_complete: true }),
    })
    checklistUpdateMock.mockResolvedValue({ summary: summary(), checklist: checklist() })
    const wrapper = mountTab('time_materials')
    await flushPromises()

    await item(wrapper, 'materials_complete').setValue(false)
    await flushPromises()

    expect(checklistUpdateMock).toHaveBeenCalledWith(
      { materials_complete: false },
      { params: { job_id: 'job-1' } },
    )
  })

  it('reverts the box and warns the user when the save fails', async () => {
    checklistUpdateMock.mockRejectedValue(new Error('nope'))
    const wrapper = mountTab('time_materials')
    await flushPromises()

    await item(wrapper, 'materials_complete').setValue(true)
    await flushPromises()

    expect(toastErrorMock).toHaveBeenCalledWith('Failed to save checklist')
    expect((item(wrapper, 'materials_complete').element as HTMLInputElement).checked).toBe(false)
  })

  it('does not hide the invoice action behind the checklist', async () => {
    const wrapper = mountTab('time_materials')
    await flushPromises()

    expect((item(wrapper, 'customer_approval_confirmed').element as HTMLInputElement).checked).toBe(
      false,
    )
    expect(wrapper.find('[data-automation-id="JobFinishTab-create-invoice"]').exists()).toBe(true)
  })

  it('names who last changed a confirmation', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary(),
      checklist: checklist({
        customer_approval_confirmed: true,
        updated_by_name: 'Office Person',
        updated_at: '2026-08-01T09:00:00Z',
      }),
    })
    const wrapper = mountTab('time_materials')
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobFinishTab-checklist"]').text()).toContain(
      'Office Person',
    )
  })
})
