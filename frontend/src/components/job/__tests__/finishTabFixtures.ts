import { vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Component } from 'vue'

/** Shared fixtures for the JobFinishTab specs, which all mount the same tree. */

const baseFinishSummary = {
  job_value_excl_gst: 1000,
  valid_invoiced_excl_gst: 400,
  outstanding_invoiced_incl_gst: 460,
  remaining_to_invoice_excl_gst: 600,
  remaining_gst: 90,
  remaining_to_invoice_incl_gst: 690,
  total_to_pay_incl_gst: 1150,
  over_invoiced_excl_gst: 0,
}

const baseChecklistState = {
  foreman_signed_off: false,
  timesheets_collected: false,
  materials_checked: false,
  customer_called: false,
  released: false,
}

// Typed against the base shapes so a typo in an override is a compile error
// rather than a silently ignored key that leaves the default in place.
export const finishSummary = (overrides: Partial<typeof baseFinishSummary> = {}) => ({
  ...baseFinishSummary,
  ...overrides,
})

export const checklistState = (overrides: Partial<typeof baseChecklistState> = {}) => ({
  ...baseChecklistState,
  ...overrides,
})

export const CHECKLIST_ITEMS = [
  'foreman_signed_off',
  'timesheets_collected',
  'materials_checked',
  'customer_called',
  'released',
] as const

export const costSummary = (
  hours: { estimate: number; quote: number; actual: number } = {
    estimate: 10,
    quote: 12,
    actual: 11,
  },
) => ({
  estimate: { cost: 500, rev: 800, hours: hours.estimate, profitMargin: 60 },
  quote: hours.quote > 0 ? { cost: 600, rev: 1000, hours: hours.quote, profitMargin: 66 } : null,
  actual: { cost: 550, rev: 900, hours: hours.actual, profitMargin: 63 },
})

let mounted: ReturnType<typeof mount> | null = null

export function mountFinishTab(
  component: Component,
  pricingMethodology = 'fixed_price',
  jobStatus = 'in_progress',
) {
  // Mounted to document.body because the invoice modal renders through a
  // reka-ui portal; resetFinishTab() must run in afterEach or the next test
  // finds the previous modal.
  mounted = mount(component, {
    props: { jobId: 'job-1', pricingMethodology, jobStatus },
    attachTo: document.body,
  })
  return mounted
}

export function resetFinishTab() {
  mounted?.unmount()
  mounted = null
  document.body.innerHTML = ''
}

export const inModal = (id: string) =>
  document.body.querySelector<HTMLElement>(`[data-automation-id="${id}"]`)

export const modalText = (id: string) => {
  const el = inModal(id)
  if (!el) throw new Error(`${id} is not in the modal`)
  return el.textContent ?? ''
}

/** The api-client mock shape every JobFinishTab spec needs. */
export const finishTabApiMocks = () => ({
  finishRetrieveMock: vi.fn(),
  invoicesRetrieveMock: vi.fn(),
  costsSummaryRetrieveMock: vi.fn(),
  checklistUpdateMock: vi.fn(),
  createInvoiceMock: vi.fn(),
  deleteInvoiceMock: vi.fn(),
  toastErrorMock: vi.fn(),
})
