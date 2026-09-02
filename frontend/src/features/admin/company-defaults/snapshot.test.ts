import { describe, expect, it } from 'vitest'

import type { CompanyDefaultsOut, SettingsFieldOut } from '@/api'

import {
  buildPatch,
  dirtyKeys,
  fromDateTimeLocalInput,
  snapshotSection,
  toDateTimeLocalInput,
} from './snapshot'

const field = (key: string, overrides: Partial<SettingsFieldOut> = {}): SettingsFieldOut => ({
  key,
  label: key,
  type: 'text',
  required: false,
  help_text: '',
  section: 'company',
  read_only: false,
  ...overrides,
})

/** The whole wire response, not a stub: `snapshotSection` takes the real
 *  `CompanyDefaultsOut`, so a column added to the model surfaces here as a type
 *  error rather than as a section that silently renders one field short. Only
 *  the keys the tests below name carry meaningful values. */
const defaults: CompanyDefaultsOut = {
  accounting_provider: 'Xero',
  address_line1: null,
  address_line2: null,
  address_raw_json: null,
  formatted_address: null,
  google_place_id: null,
  latitude: null,
  longitude: null,
  region: null,
  labour_cost_loading: '0.00',
  city: null,
  company_acronym: null,
  company_email: null,
  company_name: 'DocketWorks',
  company_url: null,
  country: 'New Zealand',
  created_at: '2026-08-21T09:30:45.123456Z',
  daily_approved_hours_target: '0.00',
  enable_xero_sync: false,
  financial_year_start_month: 7,
  fri_end: '15:30:00',
  fri_start: '07:00:00',
  gdrive_how_we_work_folder_id: null,
  gdrive_quotes_folder_id: null,
  gdrive_quotes_folder_url: null,
  gdrive_reference_library_folder_id: null,
  gdrive_sops_folder_id: null,
  google_shared_drive_id: null,
  gst_rate: '0.00',
  id: null,
  job_delta_soft_fail: false,
  kpi_daily_billable_hours_amber: '',
  kpi_daily_billable_hours_green: '',
  kpi_daily_gp_amber: '',
  kpi_daily_gp_green: '',
  kpi_daily_gp_target: '0.00',
  kpi_daily_shop_hours_percentage: '0.00',
  kpi_job_gp_target_percentage: '0.00',
  last_xero_deep_sync: null,
  last_xero_sync: '2026-08-21T09:30:45.123456Z',
  logo_url: null,
  logo_wide_url: null,
  master_quote_template_id: null,
  master_quote_template_url: null,
  materials_markup: '0.00',
  mon_end: '15:30:00',
  mon_start: '07:00:00',
  po_prefix: 'PO-',
  post_code: null,
  shop_company: 'uuid-1',
  starting_job_number: 0,
  starting_po_number: 0,
  suburb: null,
  test_company_name: null,
  thu_end: '15:30:00',
  thu_start: '07:00:00',
  time_markup: '0.00',
  tue_end: '15:30:00',
  tue_start: '07:00:00',
  updated_at: '2026-08-21T09:30:45.123456Z',
  wage_rate: '32.00',
  wed_end: '15:30:00',
  wed_start: '07:00:00',
  weekend_timesheets_enabled: false,
  workshop_efficiency_factor: '0.00',
  xero_automated_day_floor: 0,
  xero_payroll_calendar_id: null,
  xero_payroll_calendar_name: 'Weekly',
  xero_payroll_start_date: null,
  xero_quote_terms: 'Valid for 30 days.',
  xero_sales_branding_theme_id: null,
  xero_shortcode: null,
  xero_tenant_id: null,
}

describe('snapshotSection', () => {
  it('takes wire values for the section fields only', () => {
    const snap = snapshotSection(defaults, [field('company_name'), field('company_acronym')])
    expect(snap).toEqual({ company_name: 'DocketWorks', company_acronym: null })
  })
  it('reads the company widget value from the read key (shop_company)', () => {
    const snap = snapshotSection(defaults, [field('shop_company', { type: 'company' })])
    expect(snap).toEqual({ shop_company: 'uuid-1' })
  })
  it('normalises time values to HH:MM so drafts compare equal to inputs', () => {
    const snap = snapshotSection(defaults, [field('mon_start', { type: 'time' })])
    expect(snap).toEqual({ mon_start: '07:00' })
  })
  it('represents image fields by their url companion, read-only', () => {
    const snap = snapshotSection(defaults, [field('logo', { type: 'image' })])
    expect(snap).toEqual({ logo: null })
  })
  it('normalises datetime values to the minute the input can express', () => {
    const snap = snapshotSection(defaults, [field('last_xero_sync', { type: 'datetime' })])
    expect(snap).toEqual({ last_xero_sync: '2026-08-21T09:30:00.000Z' })
  })
})

// ADR 0046: Decimals travel as strings and the form never reformats a number it
// is not editing. '32.00' must survive as '32.00' — a Number() round trip would
// show the admin '32' and post a value they never typed.
describe('decimal fidelity', () => {
  it('keeps a decimal wire string byte-for-byte', () => {
    const snap = snapshotSection(defaults, [field('wage_rate', { type: 'number' })])
    expect(snap).toEqual({ wage_rate: '32.00' })
  })
  it('patches an edited decimal exactly as typed', () => {
    const fields = [field('wage_rate', { type: 'number' })]
    const server = snapshotSection(defaults, fields)
    expect(buildPatch(fields, { ...server, wage_rate: '33.50' }, server)).toEqual({
      wage_rate: '33.50',
    })
  })
  it('leaves an integer field clean once its draft is typed back to the original', () => {
    // Ints arrive as wire numbers and leave the input as strings, so the
    // snapshot holds the string form on both sides; otherwise edit-and-revert
    // stayed dirty forever on Object.is('7', 7).
    const fields = [field('financial_year_start_month', { type: 'number' })]
    const server = snapshotSection(defaults, fields)
    expect(server).toEqual({ financial_year_start_month: '7' })
    const reverted = { ...server, financial_year_start_month: '7' }
    expect(dirtyKeys(fields, reverted, server)).toEqual([])
  })
})

describe('datetime-local conversion', () => {
  it('round-trips a wire instant through the input representation', () => {
    const local = toDateTimeLocalInput('2026-08-21T09:30:45.123Z')
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
    expect(fromDateTimeLocalInput(local)).toBe('2026-08-21T09:30:00.000Z')
  })
  it('refuses a value it cannot parse instead of rendering a wrong instant', () => {
    expect(() => toDateTimeLocalInput('not-a-datetime')).toThrow(/not-a-datetime/)
    expect(() => fromDateTimeLocalInput('not-a-datetime')).toThrow(/not-a-datetime/)
  })
  it('leaves a datetime field clean when the value round-trips untouched', () => {
    const fields = [field('last_xero_sync', { type: 'datetime' })]
    const server = snapshotSection(defaults, fields)
    const displayed = toDateTimeLocalInput(String(server.last_xero_sync))
    const drafts = { ...server, last_xero_sync: fromDateTimeLocalInput(displayed) }
    expect(dirtyKeys(fields, drafts, server)).toEqual([])
  })
})

describe('dirtyKeys / buildPatch', () => {
  const fields = [
    field('company_name', { read_only: true }),
    field('company_acronym'),
    field('shop_company', { type: 'company' }),
    field('logo', { type: 'image' }),
  ]
  const server = snapshotSection(defaults, fields)

  it('is empty when drafts match the server snapshot', () => {
    expect(dirtyKeys(fields, { ...server }, server)).toEqual([])
  })
  it('ignores read_only and image fields even if their draft drifts', () => {
    const drafts = { ...server, company_name: 'X', logo: 'poked' }
    expect(dirtyKeys(fields, drafts, server)).toEqual([])
  })
  it('patches only dirty fields, mapping the company key to its write name', () => {
    const drafts = { ...server, company_acronym: 'DW', shop_company: 'uuid-2' }
    expect(buildPatch(fields, drafts, server)).toEqual({
      company_acronym: 'DW',
      // Opus: the wire reads shop_company but writes shop_company_id
      shop_company_id: 'uuid-2',
    })
  })
  it('sends google_place_id, which the page carries but never draws', () => {
    // The address picker is the only thing that sets it, and
    // CompanyDefaultsPage keeps it out of the drawn grid (UNDRAWN_KEYS). It has
    // to survive buildPatch anyway: it is what the server re-reads the geocode
    // from, so dropping it from the section would silently stop the address
    // ever being geocoded.
    const withPlaceId = [...fields, field('google_place_id')]
    const base = snapshotSection(defaults, withPlaceId)
    const drafts = { ...base, google_place_id: 'ChIJCTlhFsxIDW0RYNfpF_7ReVA' }

    expect(buildPatch(withPlaceId, drafts, base)).toEqual({
      google_place_id: 'ChIJCTlhFsxIDW0RYNfpF_7ReVA',
    })
  })
  it('sends null, never empty string, for a cleared optional field', () => {
    const drafts = { ...server, company_acronym: '' }
    expect(buildPatch(fields, drafts, server)).toEqual({ company_acronym: null })
  })
  it('sends the empty string a cleared REQUIRED field carries, so the server refuses it', () => {
    // Null would be a lie the backend accepts on some columns; '' earns the 422
    // that tells the admin the field is mandatory (fail loudly, ADR 0015).
    const requiredFields = [field('country', { required: true })]
    const requiredServer = snapshotSection(defaults, requiredFields)
    expect(buildPatch(requiredFields, { ...requiredServer, country: '' }, requiredServer)).toEqual({
      country: '',
    })
  })
})
