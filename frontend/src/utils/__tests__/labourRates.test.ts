import { describe, it, expect } from 'vitest'
import {
  LABOUR_ITEM_PREFIX,
  labourItemId,
  nextLabourDesc,
  parseLabourItemId,
  rateForSubtype,
  subtypeName,
  workshopRateEntry,
  type JobLabourRate,
} from '../labourRates'

const WORKSHOP_ID = '11111111-1111-4111-8111-111111111111'
const ADMIN_ID = '22222222-2222-4222-8222-222222222222'
const ONSITE_ID = '33333333-3333-4333-8333-333333333333'

const rates: JobLabourRate[] = [
  {
    id: 'aaaaaaaa-0000-4000-8000-000000000001',
    labour_subtype: WORKSHOP_ID,
    labour_subtype_name: 'Workshop',
    is_workshop: true,
    charge_out_rate: 105,
  },
  {
    id: 'aaaaaaaa-0000-4000-8000-000000000002',
    labour_subtype: ADMIN_ID,
    labour_subtype_name: 'Admin',
    is_workshop: false,
    charge_out_rate: 90,
  },
  {
    id: 'aaaaaaaa-0000-4000-8000-000000000003',
    labour_subtype: ONSITE_ID,
    labour_subtype_name: 'Onsite',
    is_workshop: false,
    charge_out_rate: 120,
  },
]

const workshopRate = rates[0]
const adminRate = rates[1]

describe('labourItemId / parseLabourItemId', () => {
  it('round-trips a subtype uuid', () => {
    const id = labourItemId(WORKSHOP_ID)
    expect(id).toBe(`${LABOUR_ITEM_PREFIX}${WORKSHOP_ID}`)
    expect(parseLabourItemId(id)).toBe(WORKSHOP_ID)
  })

  it('returns null for non-labour values', () => {
    expect(parseLabourItemId(WORKSHOP_ID)).toBeNull() // plain stock uuid
    expect(parseLabourItemId('not-a-labour-id')).toBeNull()
    expect(parseLabourItemId(null)).toBeNull()
    expect(parseLabourItemId('')).toBeNull()
  })
})

describe('subtypeName', () => {
  it('resolves the name for a known subtype', () => {
    expect(subtypeName(rates, ADMIN_ID)).toBe('Admin')
  })

  it('returns null for unknown, null, and undefined subtypes', () => {
    expect(subtypeName(rates, '99999999-9999-4999-8999-999999999999')).toBeNull()
    expect(subtypeName(rates, null)).toBeNull()
    expect(subtypeName(rates, undefined)).toBeNull()
    expect(subtypeName([], WORKSHOP_ID)).toBeNull()
  })
})

describe('nextLabourDesc', () => {
  it('replaces an empty/whitespace description with the subtype name', () => {
    expect(nextLabourDesc('', adminRate, rates)).toBe('Admin')
    expect(nextLabourDesc('   ', adminRate, rates)).toBe('Admin')
  })

  it("replaces the legacy 'Labour' prefill", () => {
    expect(nextLabourDesc('Labour', adminRate, rates)).toBe('Admin')
  })

  it('replaces a description that is still another subtype-name prefill', () => {
    expect(nextLabourDesc('Workshop', adminRate, rates)).toBe('Admin')
    expect(nextLabourDesc('Onsite', workshopRate, rates)).toBe('Workshop')
  })

  it('preserves user-authored text', () => {
    expect(nextLabourDesc('Fold and weld the cabinet', adminRate, rates)).toBe(
      'Fold and weld the cabinet',
    )
  })
})

describe('workshopRateEntry', () => {
  it('returns the is_workshop entry', () => {
    expect(workshopRateEntry(rates)).toBe(workshopRate)
  })

  it('falls back to the first entry when no workshop entry exists', () => {
    const noWorkshop = rates.filter((r) => !r.is_workshop)
    expect(workshopRateEntry(noWorkshop)).toBe(noWorkshop[0])
  })

  it('returns undefined for an empty list', () => {
    expect(workshopRateEntry([])).toBeUndefined()
  })
})

describe('rateForSubtype', () => {
  it('returns the rate for a known subtype', () => {
    expect(rateForSubtype(rates, ONSITE_ID)).toBe(120)
  })

  it('uses the workshop rate when the subtype is unset', () => {
    expect(rateForSubtype(rates, null)).toBe(105)
  })

  it('throws when the subtype is unknown', () => {
    expect(() => rateForSubtype(rates, '99999999-9999-4999-8999-999999999999')).toThrow(
      'No job labour rate for subtype',
    )
  })

  it('treats an empty subtype id as invalid instead of falling back to workshop', () => {
    expect(() => rateForSubtype(rates, '')).toThrow('No job labour rate for subtype')
  })

  it('throws when no rates are loaded', () => {
    expect(() => rateForSubtype([], WORKSHOP_ID)).toThrow('No job labour rate for subtype')
  })
})
