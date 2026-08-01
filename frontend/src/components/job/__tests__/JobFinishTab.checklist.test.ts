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

const checklist = (overrides: Record<string, boolean> = {}) => ({
  foreman_signed_off: false,
  timesheets_collected: false,
  materials_checked: false,
  customer_called: false,
  released: false,
  ...overrides,
})

const ITEMS = [
  'foreman_signed_off',
  'timesheets_collected',
  'materials_checked',
  'customer_called',
  'released',
]

let mounted: ReturnType<typeof mount> | null = null

function mountTab(pricingMethodology = 'fixed_price') {
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

  it('asks the same five questions on a quoted job', async () => {
    const wrapper = mountTab('fixed_price')
    await flushPromises()

    for (const key of ITEMS) {
      expect(item(wrapper, key).exists()).toBe(true)
    }
  })

  it('asks the same five questions on a T&M job', async () => {
    const wrapper = mountTab('time_materials')
    await flushPromises()

    for (const key of ITEMS) {
      expect(item(wrapper, key).exists()).toBe(true)
    }
  })

  it('warns that time and materials are what a T&M customer pays', async () => {
    const wrapper = mountTab('time_materials')
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobFinishTab-tm-urgency"]').text()).toContain(
      'before invoicing',
    )
  })

  it('does not show the T&M urgency note on a quoted job', async () => {
    const wrapper = mountTab('fixed_price')
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobFinishTab-tm-urgency"]').exists()).toBe(false)
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
