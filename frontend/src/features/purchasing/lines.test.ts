import { describe, expect, it } from 'vitest'

import {
  draftCreateBody,
  emptyPoLineDraft,
  poLineDraftIsEmpty,
  poLineDraftIsReady,
  poLineItemLabel,
} from './lines'

describe('PO line drafts', () => {
  it('a fresh draft is empty and not ready', () => {
    const draft = emptyPoLineDraft()
    expect(poLineDraftIsEmpty(draft)).toBe(true)
    expect(poLineDraftIsReady(draft)).toBe(false)
  })

  it('an item pick makes the draft non-empty and ready', () => {
    const draft = { ...emptyPoLineDraft(), description: '5mm Round Bar', unit_cost: '12.50' }
    expect(poLineDraftIsEmpty(draft)).toBe(false)
    expect(poLineDraftIsReady(draft)).toBe(true)
  })

  it('a whitespace-only description is not ready', () => {
    const draft = { ...emptyPoLineDraft(), description: '   ' }
    expect(poLineDraftIsReady(draft)).toBe(false)
  })

  it('a job pick alone makes the draft non-empty but not ready', () => {
    const draft = { ...emptyPoLineDraft(), job_id: 'job-1', job_number: 42, job_name: 'X' }
    expect(poLineDraftIsEmpty(draft)).toBe(false)
    expect(poLineDraftIsReady(draft)).toBe(false)
  })

  it('the create body carries only the set fields — unset nullables stay absent', () => {
    const body = draftCreateBody({ ...emptyPoLineDraft(), description: 'Bar', quantity: '5' })
    expect(body).toEqual({ description: 'Bar', quantity: '5' })
    // Key absence matters, not just undefined values: the endpoint writes
    // exactly the keys present, and NullableText columns 422 on ''.
    expect('unit_cost' in body).toBe(false)
    expect('item_code' in body).toBe(false)
    expect('job_id' in body).toBe(false)
  })

  it('the create body carries every set field and no id', () => {
    const body = draftCreateBody({
      description: 'Bar',
      quantity: '5',
      unit_cost: '12.50',
      item_code: 'RB5',
      metal_type: 'steel',
      alloy: '304',
      specifics: 'h9',
      location: 'A1',
      job_id: 'job-1',
      job_number: 42,
      job_name: 'X',
    })
    expect(body).toEqual({
      description: 'Bar',
      quantity: '5',
      unit_cost: '12.50',
      item_code: 'RB5',
      metal_type: 'steel',
      alloy: '304',
      specifics: 'h9',
      location: 'A1',
      job_id: 'job-1',
    })
    expect('id' in body).toBe(false)
    // Display-only job facts never reach the wire.
    expect('job_number' in body).toBe(false)
    expect('job_name' in body).toBe(false)
  })
})

describe('poLineItemLabel', () => {
  it('prefers the item code when one is bound', () => {
    expect(poLineItemLabel('RB5', 'Round bar 5mm')).toBe('RB5')
  })

  it('falls back to the description for a bound item with no code', () => {
    // Regression: item_code is nullable (v1 parity), so a bound line with
    // no code must not read as unbound.
    expect(poLineItemLabel(null, 'Round bar 5mm')).toBe('Round bar 5mm')
  })

  it('reads as unbound only when neither a code nor a description is set', () => {
    expect(poLineItemLabel(null, '')).toBe('Select Item')
    expect(poLineItemLabel(null, '   ')).toBe('Select Item')
  })
})
