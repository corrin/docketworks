import { describe, expect, it } from 'vitest'

import type { CostLineOut, JobLabourRateOut, StockItem } from '@/api'
import {
  derivedUnitRev,
  isDraftReadyToPersist,
  itemLabel,
  labourPickPatch,
  parseDecimalInput,
  stockPickPatch,
  trimDecimal,
} from './calc'
import { emptyDraft } from './types'

const line = (overrides: Partial<CostLineOut> = {}): CostLineOut => ({
  accounting_date: '2026-08-09',
  approved: false,
  created_at: '2026-08-09T00:00:00Z',
  desc: 'Existing line',
  entry_seq: null,
  ext_refs: {},
  id: 'line-1',
  kind: 'material',
  labour_subtype: null,
  meta: {},
  quantity: '1.000',
  staff: null,
  total_cost: 10,
  total_rev: 12,
  unit_cost: '10.00',
  unit_rev: '12.00',
  updated_at: '2026-08-09T00:00:00Z',
  xero_expense_id: null,
  xero_last_modified: null,
  xero_last_synced: null,
  xero_pay_item: null,
  xero_time_id: null,
  ...overrides,
})

const stock = (overrides: Partial<StockItem> = {}): StockItem => ({
  alloy: null,
  date: '2026-08-01',
  description: 'Steel plate 3mm',
  id: 'stock-1',
  is_active: true,
  item_code: 'SP3',
  job_id: null,
  location: null,
  metal_type: null,
  quantity: '4.000',
  source: 'purchase',
  specifics: null,
  times_used: 2,
  unit_cost: '40.00',
  unit_revenue: '55.00',
  ...overrides,
})

const labourRate = (overrides: Partial<JobLabourRateOut> = {}): JobLabourRateOut => ({
  charge_out_rate: '105.00',
  id: 'rate-1',
  is_workshop: true,
  labour_subtype: 'workshop',
  labour_subtype_name: 'Workshop',
  ...overrides,
})

describe('parseDecimalInput', () => {
  it('accepts plain and comma-grouped numbers', () => {
    expect(parseDecimalInput('1,250.50')).toBe('1250.50')
    expect(parseDecimalInput(' 3 ')).toBe('3')
  })

  it('returns null for garbage and non-finite input', () => {
    expect(parseDecimalInput('abc')).toBeNull()
    expect(parseDecimalInput('')).toBeNull()
    expect(parseDecimalInput('Infinity')).toBeNull()
  })
})

describe('trimDecimal', () => {
  it('strips trailing zeros for input display', () => {
    expect(trimDecimal('3.000')).toBe('3')
    expect(trimDecimal('25.00')).toBe('25')
    expect(trimDecimal('1000.50')).toBe('1000.5')
    expect(trimDecimal('0.2500')).toBe('0.25')
  })

  it('leaves non-decimal strings alone', () => {
    expect(trimDecimal('')).toBe('')
    expect(trimDecimal('12')).toBe('12')
  })
})

describe('derivedUnitRev', () => {
  it('applies the materials markup at two decimal places', () => {
    expect(derivedUnitRev('100.00', '0.2000')).toBe('120.00')
  })
})

describe('stockPickPatch', () => {
  it('merges ext_refs instead of replacing them', () => {
    // The backend replaces ext_refs wholesale, so the patch must carry every
    // existing key or the write silently drops them.
    const patch = stockPickPatch(line({ ext_refs: { po_line_id: 'po-9' } }), stock(), '0.2000')

    expect(patch.ext_refs).toEqual({ po_line_id: 'po-9', stock_id: 'stock-1' })
    expect(patch.kind).toBe('material')
    expect(patch.desc).toBe('Steel plate 3mm')
    expect(patch.unit_cost).toBe('40.00')
    expect(patch.unit_rev).toBe('55.00')
    expect(patch.labour_subtype).toBeNull()
  })

  it('derives unit_rev from markup when the stock item has no revenue', () => {
    const patch = stockPickPatch(line(), stock({ unit_revenue: null }), '0.2000')

    expect(patch.unit_rev).toBe('48.00')
  })
})

describe('labourPickPatch', () => {
  it('converts the line to time at the job charge-out rate and drops stock_id', () => {
    const patch = labourPickPatch(line({ ext_refs: { stock_id: 'stock-1', keep: 'yes' } }), {
      rate: labourRate(),
      wageRate: '38.00',
    })

    expect(patch.kind).toBe('time')
    expect(patch.labour_subtype).toBe('workshop')
    expect(patch.desc).toBe('Workshop')
    expect(patch.unit_cost).toBe('38.00')
    expect(patch.unit_rev).toBe('105.00')
    expect(patch.ext_refs).toEqual({ keep: 'yes' })
  })
})

describe('itemLabel', () => {
  const stockById = new Map([[stock().id, stock()]])
  const rates = [labourRate()]

  it('is "Select Item" for an unbound non-time line', () => {
    expect(itemLabel(line(), stockById, rates)).toBe('Select Item')
  })

  it('names the stock item when bound', () => {
    expect(itemLabel(line({ ext_refs: { stock_id: 'stock-1' } }), stockById, rates)).toBe('SP3')
  })

  it('names the labour subtype for a time line', () => {
    expect(itemLabel(line({ kind: 'time', labour_subtype: 'workshop' }), stockById, rates)).toBe(
      'Workshop',
    )
  })
})

describe('isDraftReadyToPersist', () => {
  it('requires description, positive quantity, and both unit amounts', () => {
    const ready = {
      ...emptyDraft(),
      desc: 'New line',
      quantity: '2',
      unit_cost: '10.00',
      unit_rev: '12.00',
    }
    expect(isDraftReadyToPersist(ready)).toBe(true)
    expect(isDraftReadyToPersist({ ...ready, desc: '  ' })).toBe(false)
    expect(isDraftReadyToPersist({ ...ready, quantity: '0' })).toBe(false)
    expect(isDraftReadyToPersist({ ...ready, unit_cost: null })).toBe(false)
    expect(isDraftReadyToPersist({ ...ready, unit_rev: null })).toBe(false)
  })
})
