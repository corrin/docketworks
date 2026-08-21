import { describe, expect, it } from 'vitest'

import type { SettingsFieldOut } from '@/api'

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

// Only the fields under test; the functions never touch other keys.
const defaults = {
  company_name: 'DocketWorks',
  company_acronym: null,
  shop_company: 'uuid-1',
  mon_start: '07:00:00',
  wage_rate: '32.00',
  logo_url: null,
  last_xero_sync: '2026-08-21T09:30:45.123456Z',
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
  it('sends null, never empty string, for a cleared optional field', () => {
    const drafts = { ...server, company_acronym: '' }
    expect(buildPatch(fields, drafts, server)).toEqual({ company_acronym: null })
  })
})
