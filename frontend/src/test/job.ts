import type { JobDetail, JobFinishResponse } from '@/api'

const baseJob: JobDetail = {
  company_id: null,
  company_name: null,
  created_at: '2026-08-08T00:00:00Z',
  default_xero_pay_item_id: null,
  default_xero_pay_item_name: null,
  delivery_date: null,
  description: null,
  fully_invoiced: false,
  id: 'job-1',
  invoices: [],
  is_urgent: false,
  job_files: [],
  job_is_valid: true,
  job_number: 1,
  job_status: 'draft',
  latest_actual: null,
  latest_estimate: null,
  latest_quote: null,
  max_people: 1,
  min_people: 1,
  name: 'Test job',
  notes: null,
  order_number: null,
  paid: false,
  person_id: null,
  person_name: null,
  price_cap: null,
  pricing_methodology: 'fixed_price',
  quote: null,
  quote_acceptance_date: null,
  quote_sheet: null,
  quoted: false,
  rdti_type: null,
  rejected_flag: false,
  shop_job: false,
  speed_quality_tradeoff: 'normal',
  updated_at: '2026-08-08T00:00:00Z',
  xero_invoices: [],
  xero_quote: null,
}

export const finishPayload: JobFinishResponse = {
  summary: {
    job_value_excl_gst: '1000.00',
    valid_invoiced_excl_gst: '0.00',
    outstanding_invoiced_incl_gst: '0.00',
    remaining_to_invoice_excl_gst: '1000.00',
    remaining_gst: '150.00',
    remaining_to_invoice_incl_gst: '1150.00',
    total_to_pay_incl_gst: '1150.00',
    over_invoiced_excl_gst: '0.00',
  },
  checklist: {
    foreman_signed_off: false,
    timesheets_collected: false,
    materials_checked: false,
    customer_called: false,
    released: false,
  },
}

export function jobDetail(overrides: Partial<JobDetail> = {}): JobDetail {
  return { ...baseJob, ...overrides }
}
