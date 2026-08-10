import { describe, expect, it } from 'vitest'

import type { TimesheetJobOut } from '@/api'
import {
  applyJobPick,
  draftIsEmpty,
  draftIsReady,
  emptyTimesheetDraft,
  type TimesheetDraft,
} from './timesheetDraft'

function makeJob(overrides: Partial<TimesheetJobOut> = {}): TimesheetJobOut {
  return {
    id: 'job-1',
    job_number: 101,
    name: 'Fabricate frame',
    company_name: 'ABC',
    status: 'in_progress',
    labour_rates: [],
    has_actual_costset: true,
    leave_type: null,
    estimated_hours: null,
    default_xero_pay_item_id: 'pay-ordinary',
    default_xero_pay_item_name: 'Ordinary Time',
    shop_job: false,
    is_urgent: false,
    ...overrides,
  }
}

const normalJob = makeJob()
const urgentJob = makeJob({ id: 'job-2', job_number: 202, is_urgent: true })
const shopJob = makeJob({ id: 'job-3', job_number: 303, shop_job: true })
const urgentShopJob = makeJob({ id: 'job-4', job_number: 404, shop_job: true, is_urgent: true })
const specialJob = makeJob({ id: 'job-5', job_number: 505, status: 'special' })

describe('draft lifecycle predicates', () => {
  it('a fresh draft is empty and not ready', () => {
    const draft = emptyTimesheetDraft()
    expect(draftIsEmpty(draft)).toBe(true)
    expect(draftIsReady(draft)).toBe(false)
  })

  it('a job alone is not ready; job plus hours is', () => {
    const withJob = { ...emptyTimesheetDraft(), job: normalJob }
    expect(draftIsEmpty(withJob)).toBe(false)
    expect(draftIsReady(withJob)).toBe(false)
    expect(draftIsReady({ ...withJob, hours: 2 })).toBe(true)
  })
})

describe('applyJobPick precedence (v1 urgent + bill-reset cases)', () => {
  it('an urgent job defaults bill to 1.5 and leaves the wage at ordinary', () => {
    const picked = applyJobPick(emptyTimesheetDraft(), urgentJob)
    expect(picked.bill_rate_multiplier).toBe(1.5)
    expect(picked.wage_rate_multiplier).toBe(1.0)
    expect(picked.is_billable).toBe(true)
  })

  it('a normal job defaults bill to 1.0', () => {
    const picked = applyJobPick(emptyTimesheetDraft(), normalJob)
    expect(picked.bill_rate_multiplier).toBe(1.0)
    expect(picked.is_billable).toBe(true)
  })

  it('repicking urgent → normal resets the stale 1.5', () => {
    const afterUrgent = applyJobPick(emptyTimesheetDraft(), urgentJob)
    const afterNormal = applyJobPick(afterUrgent, normalJob)
    expect(afterNormal.bill_rate_multiplier).toBe(1.0)
  })

  it('a shop job is non-billable and wins over urgent', () => {
    const picked = applyJobPick(emptyTimesheetDraft(), urgentShopJob)
    expect(picked.is_billable).toBe(false)
    expect(picked.bill_rate_multiplier).toBe(0.0)
  })

  it('status special is non-billable', () => {
    const picked = applyJobPick(emptyTimesheetDraft(), specialJob)
    expect(picked.is_billable).toBe(false)
    expect(picked.bill_rate_multiplier).toBe(0.0)
  })

  it('shop wins even over an explicit override', () => {
    const explicit: TimesheetDraft = {
      ...emptyTimesheetDraft(),
      bill_rate_multiplier: 2.0,
      billExplicit: true,
    }
    const picked = applyJobPick(explicit, shopJob)
    expect(picked.bill_rate_multiplier).toBe(0.0)
    expect(picked.is_billable).toBe(false)
  })

  it('an explicit override survives a normal repick', () => {
    const explicit: TimesheetDraft = {
      ...emptyTimesheetDraft(),
      bill_rate_multiplier: 2.0,
      billExplicit: true,
    }
    const picked = applyJobPick(explicit, urgentJob)
    expect(picked.bill_rate_multiplier).toBe(2.0)
  })

  it('the wage multiplier is never changed by a pick', () => {
    const draft: TimesheetDraft = { ...emptyTimesheetDraft(), wage_rate_multiplier: 1.5 }
    expect(applyJobPick(draft, urgentJob).wage_rate_multiplier).toBe(1.5)
    expect(applyJobPick(draft, shopJob).wage_rate_multiplier).toBe(1.5)
  })
})
