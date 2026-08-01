import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'

const {
  finishRetrieveMock,
  invoicesRetrieveMock,
  costsSummaryRetrieveMock,
  createInvoiceMock,
  deleteInvoiceMock,
} = vi.hoisted(() => ({
  finishRetrieveMock: vi.fn(),
  invoicesRetrieveMock: vi.fn(),
  costsSummaryRetrieveMock: vi.fn(),
  createInvoiceMock: vi.fn(),
  deleteInvoiceMock: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_finish_retrieve: finishRetrieveMock,
    job_jobs_invoices_retrieve: invoicesRetrieveMock,
    job_jobs_costs_summary_retrieve: costsSummaryRetrieveMock,
    job_jobs_finish_partial_update: vi.fn(),
    xero_create_invoice_create: createInvoiceMock,
    xero_delete_invoice_destroy: deleteInvoiceMock,
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
  checklistState as checklist,
  costSummary,
  finishSummary as summary,
  inModal,
  modalText,
  mountFinishTab,
  resetFinishTab,
} from './finishTabFixtures'

/**
 * The backend owns every figure here. These tests assert the component renders
 * what the API returned and never recomputes it — the ADR 0020 boundary that
 * KAN-323 exists to restore.
 */
const mountTab = (pricingMethodology = 'fixed_price', jobStatus = 'in_progress') =>
  mountFinishTab(JobFinishTab, pricingMethodology, jobStatus)

const text = (wrapper: ReturnType<typeof mountTab>, id: string) =>
  wrapper.find(`[data-automation-id="${id}"]`).text()

async function openInvoiceModal(wrapper: ReturnType<typeof mountTab>) {
  await wrapper.find('[data-automation-id="JobFinishTab-create-invoice"]').trigger('click')
  await flushPromises()
}

describe('JobFinishTab customer balance', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    finishRetrieveMock.mockResolvedValue({ summary: summary(), checklist: checklist() })
    invoicesRetrieveMock.mockResolvedValue({ invoices: [] })
    costsSummaryRetrieveMock.mockResolvedValue(costSummary())
  })

  afterEach(resetFinishTab)

  it('renders the subtotal, GST and Total to pay returned by the API', async () => {
    const wrapper = mountTab()
    await flushPromises()

    expect(text(wrapper, 'JobFinishTab-remaining-excl-gst')).toContain('600')
    expect(text(wrapper, 'JobFinishTab-remaining-gst')).toContain('90')
    expect(text(wrapper, 'JobFinishTab-total-to-pay')).toContain('1,150')
  })

  it('does not derive Total to pay from the other figures', async () => {
    // A deliberately inconsistent payload: if the component recomputed the
    // total it would show 1,290 rather than the server's answer.
    finishRetrieveMock.mockResolvedValue({
      summary: summary({ total_to_pay_incl_gst: 42 }),
      checklist: checklist(),
    })
    const wrapper = mountTab()
    await flushPromises()

    expect(text(wrapper, 'JobFinishTab-total-to-pay')).toContain('42')
  })

  it('shows the outstanding invoice balance when Xero is still owed money', async () => {
    const wrapper = mountTab()
    await flushPromises()

    expect(text(wrapper, 'JobFinishTab-outstanding-incl-gst')).toContain('460')
  })

  it('hides the outstanding line when every invoice is paid', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary({ outstanding_invoiced_incl_gst: 0 }),
      checklist: checklist(),
    })
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobFinishTab-outstanding-incl-gst"]').exists()).toBe(
      false,
    )
  })

  it('offers no invoice action once the job is fully covered', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary({
        valid_invoiced_excl_gst: 1000,
        remaining_to_invoice_excl_gst: 0,
        remaining_gst: 0,
        remaining_to_invoice_incl_gst: 0,
        total_to_pay_incl_gst: 0,
      }),
      checklist: checklist(),
    })
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobFinishTab-create-invoice"]').exists()).toBe(false)
    expect(wrapper.find('[data-automation-id="JobFinishTab-fully-invoiced"]').exists()).toBe(true)
  })

  it('shows an error instead of a zero balance when the load fails', async () => {
    // Regression: the catch used to clear `loading` while leaving a fabricated
    // zero summary on screen, so a failed request read as a settled job.
    finishRetrieveMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobFinishTab-load-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-automation-id="JobFinishTab-total-to-pay"]').exists()).toBe(false)
    expect(wrapper.find('[data-automation-id="JobFinishTab-create-invoice"]').exists()).toBe(false)
  })

  it('reports an over-invoiced job instead of a negative balance', async () => {
    finishRetrieveMock.mockResolvedValue({
      summary: summary({
        job_value_excl_gst: 800,
        valid_invoiced_excl_gst: 1000,
        remaining_to_invoice_excl_gst: 0,
        remaining_gst: 0,
        remaining_to_invoice_incl_gst: 0,
        outstanding_invoiced_incl_gst: 0,
        total_to_pay_incl_gst: 0,
        over_invoiced_excl_gst: 200,
      }),
      checklist: checklist(),
    })
    const wrapper = mountTab()
    await flushPromises()

    expect(text(wrapper, 'JobFinishTab-over-invoiced')).toContain('200')
  })

  it('re-reads the balance from the server after creating an invoice', async () => {
    createInvoiceMock.mockResolvedValue({ success: true, messages: [] })
    const wrapper = mountTab()
    await flushPromises()
    expect(finishRetrieveMock).toHaveBeenCalledTimes(1)

    await openInvoiceModal(wrapper)
    inModal('JobFinishTab-mode-invoice-full')!.click()
    await flushPromises()

    expect(createInvoiceMock).toHaveBeenCalled()
    expect(finishRetrieveMock).toHaveBeenCalledTimes(2)
  })

  it('re-reads the balance from the server after deleting an invoice', async () => {
    invoicesRetrieveMock.mockResolvedValue({
      invoices: [
        {
          id: 'inv-1',
          xero_id: 'xero-1',
          number: 'INV-001',
          status: 'AUTHORISED',
          date: '2026-08-01',
          total_excl_tax: 400,
          online_url: 'https://xero.example/inv-1',
        },
      ],
    })
    deleteInvoiceMock.mockResolvedValue({})
    const wrapper = mountTab()
    await flushPromises()

    await wrapper
      .findAll('button')
      .filter((b) => b.classes().join(' ').includes('h-7'))
      .at(1)!
      .trigger('click')
    await flushPromises()

    expect(deleteInvoiceMock).toHaveBeenCalled()
    expect(finishRetrieveMock).toHaveBeenCalledTimes(2)
  })
})

describe('JobFinishTab invoice modes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    finishRetrieveMock.mockResolvedValue({ summary: summary(), checklist: checklist() })
    invoicesRetrieveMock.mockResolvedValue({ invoices: [] })
    costsSummaryRetrieveMock.mockResolvedValue(costSummary())
  })

  afterEach(resetFinishTab)

  it('keeps all three fixed-price modes available', async () => {
    const wrapper = mountTab('fixed_price')
    await flushPromises()
    await openInvoiceModal(wrapper)

    expect(inModal('JobFinishTab-mode-invoice-full')).not.toBeNull()
    expect(inModal('JobFinishTab-mode-invoice-percent')).not.toBeNull()
    expect(inModal('JobFinishTab-mode-invoice-amount')).not.toBeNull()
  })

  it('keeps both T&M modes available', async () => {
    const wrapper = mountTab('time_materials')
    await flushPromises()
    await openInvoiceModal(wrapper)

    expect(inModal('JobFinishTab-mode-invoice-costs-to-date')).not.toBeNull()
    expect(inModal('JobFinishTab-mode-invoice-amount')).not.toBeNull()
    expect(inModal('JobFinishTab-mode-invoice-percent')).toBeNull()
  })

  it('offers invoicing before the work is complete', async () => {
    const wrapper = mountTab('fixed_price', 'approved')
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobFinishTab-create-invoice"]').exists()).toBe(true)
    await openInvoiceModal(wrapper)
    expect(modalText('JobFinishTab-mode-invoice-full')).toContain('in advance')
  })

  it('describes the remaining balance once the work is complete', async () => {
    const wrapper = mountTab('fixed_price', 'recently_completed')
    await flushPromises()
    await openInvoiceModal(wrapper)

    expect(modalText('JobFinishTab-mode-invoice-full')).toContain('remaining quote balance')
  })
})
