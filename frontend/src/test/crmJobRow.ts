import type { CrmJobRow, JobInvoiceRef } from '@/api'

/** One sales invoice on a job header row, as the API shapes it. */
export function jobInvoiceRef(overrides: Partial<JobInvoiceRef> = {}): JobInvoiceRef {
  return {
    id: 'inv-1',
    number: 'INV-0001',
    date: '2026-02-20',
    status: 'PAID',
    total_excl_tax: 100,
    online_url: 'https://invoices.example/inv-1',
    ...overrides,
  }
}

/** A job header row as both CRM job lists return it. */
export function crmJobRow(overrides: Partial<CrmJobRow> = {}): CrmJobRow {
  return {
    company: { id: 'company-1', name: 'Alpha Engineering' },
    fully_invoiced: false,
    has_quote_in_xero: false,
    is_fixed_price: false,
    job_id: 'job-1',
    job_number: 101,
    max_people: 1,
    min_people: 1,
    name: 'Fabricate frame',
    paid: false,
    pricing_methodology: 'time_materials',
    quote_acceptance_date: null,
    rejected_flag: false,
    speed_quality_tradeoff: 'balanced',
    status: 'in_progress',
    invoices: [],
    invoiced_total_excl_tax: 0,
    ...overrides,
  }
}
