import { describe, expect, it } from 'vitest'
import {
  calculatedBill,
  calculatedWage,
  getBillMultiplier,
  getRateMultiplier,
  getRateTypeFromMultiplier,
  parseHoursInput,
  type TimesheetCostLine,
} from '../timesheetCalc'

function makeEntry(over: Partial<TimesheetCostLine> = {}): TimesheetCostLine {
  return {
    id: 'e1',
    kind: 'time',
    desc: '',
    quantity: 0,
    unit_cost: 0,
    unit_rev: 0,
    ext_refs: {},
    meta: {},
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    accounting_date: '2026-05-01',
    xero_time_id: null,
    xero_expense_id: null,
    xero_last_modified: null,
    xero_last_synced: null,
    approved: false,
    xero_pay_item: null,
    total_cost: 0,
    total_rev: 0,
    job_id: '',
    job_number: 0,
    job_name: '',
    client_name: '',
    charge_out_rate: 0,
    wage_rate: 0,
    xero_pay_item_name: '',
    ...over,
  } as TimesheetCostLine
}

describe('timesheetCalc', () => {
  describe('calculatedWage', () => {
    it('multiplies hours × multiplier × wage_rate', () => {
      // The original bug surfaced when this exact calculation was racing with
      // an autosave snapshot, leaving hours and the multiplier zeroed at fire
      // time. Locking the formula in tests guards the regression.
      const entry = makeEntry({
        quantity: 2,
        wage_rate: 30,
        meta: { wage_rate_multiplier: 1.5 },
      })
      expect(calculatedWage(entry)).toBe(90)
    })

    it('uses unit_cost when wage_rate is missing', () => {
      const entry = makeEntry({
        quantity: 1,
        wage_rate: 0,
        unit_cost: 35,
        meta: { wage_rate_multiplier: 1.0 },
      })
      expect(calculatedWage(entry)).toBe(35)
    })

    it('returns 0 when hours is zero', () => {
      const entry = makeEntry({ quantity: 0, wage_rate: 50 })
      expect(calculatedWage(entry)).toBe(0)
    })

    it('returns 0 when wage_rate is zero', () => {
      const entry = makeEntry({ quantity: 5, wage_rate: 0 })
      expect(calculatedWage(entry)).toBe(0)
    })

    it('treats missing multiplier as Ord (1.0)', () => {
      const entry = makeEntry({ quantity: 1, wage_rate: 37.8, meta: {} })
      expect(calculatedWage(entry)).toBe(37.8)
    })

    it('respects an explicit Unpaid multiplier (0.0)', () => {
      const entry = makeEntry({
        quantity: 8,
        wage_rate: 50,
        meta: { wage_rate_multiplier: 0.0 },
      })
      expect(calculatedWage(entry)).toBe(0)
    })
  })

  describe('calculatedBill', () => {
    it('returns hours × charge_out_rate × bill multiplier', () => {
      const entry = makeEntry({
        quantity: 2,
        charge_out_rate: 100,
        meta: { is_billable: true, bill_rate_multiplier: 1.5 },
      })
      expect(calculatedBill(entry)).toBe(300)
    })

    it('returns 0 when bill multiplier is unpaid', () => {
      const entry = makeEntry({
        quantity: 2,
        charge_out_rate: 100,
        meta: { is_billable: false, bill_rate_multiplier: 0.0 },
      })
      expect(calculatedBill(entry)).toBe(0)
    })

    it('defaults missing bill multiplier to wage multiplier for legacy rows', () => {
      const entry = makeEntry({
        quantity: 1,
        charge_out_rate: 75,
        meta: { wage_rate_multiplier: 2.0 },
      })
      expect(getBillMultiplier(entry)).toBe(2.0)
      expect(calculatedBill(entry)).toBe(150)
    })

    it('defaults legacy non-billable rows to a zero bill multiplier', () => {
      const entry = makeEntry({
        quantity: 1,
        charge_out_rate: 75,
        meta: { is_billable: false, wage_rate_multiplier: 2.0 },
      })
      expect(getBillMultiplier(entry)).toBe(0.0)
      expect(calculatedBill(entry)).toBe(0)
    })
  })

  describe('rate <-> multiplier', () => {
    it('round-trips Ord/1.5/2.0/Unpaid', () => {
      for (const rt of ['Ord', '1.5', '2.0', 'Unpaid']) {
        expect(getRateTypeFromMultiplier(getRateMultiplier(rt))).toBe(rt)
      }
    })

    it('falls back to Ord for unknown multipliers', () => {
      expect(getRateTypeFromMultiplier(1.25)).toBe('Ord')
      expect(getRateTypeFromMultiplier(undefined)).toBe('Ord')
      expect(getRateTypeFromMultiplier(null)).toBe('Ord')
    })
  })

  describe('parseHoursInput', () => {
    it('parses plain decimals', () => {
      expect(parseHoursInput('1.5', 0)).toBe(1.5)
    })

    it('parses simple fractions', () => {
      expect(parseHoursInput('3/4', 0)).toBe(0.75)
    })

    it('parses mixed numbers', () => {
      expect(parseHoursInput('1 1/4', 0)).toBe(1.25)
    })

    it('returns the fallback on blank input', () => {
      expect(parseHoursInput('', 7)).toBe(7)
      expect(parseHoursInput('   ', 7)).toBe(7)
    })

    it('returns the fallback on unparseable input', () => {
      expect(parseHoursInput('hello', 3)).toBe(3)
      expect(parseHoursInput('1/0', 3)).toBe(3)
    })

    it('clamps to 24', () => {
      expect(parseHoursInput('48', 0)).toBe(24)
    })

    it('rejects negative values', () => {
      expect(parseHoursInput('-2', 1)).toBe(1)
    })
  })
})
