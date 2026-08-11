import { describe, expect, it } from 'vitest'

import type { JobForPurchasing } from '@/api'
import { filterJobs, jobSelectLabel } from './JobSelect'

function job(overrides: Partial<JobForPurchasing>): JobForPurchasing {
  const base = {
    id: 'job-1',
    job_number: 100,
    name: 'Handrail',
    company_name: 'ABC',
    status: 'draft',
    is_stock_holding: false,
    ...overrides,
  }
  // Derived like the backend derives it, so a display-name match can never
  // leak another fixture's name into a filter assertion.
  return { ...base, job_display_name: `${base.job_number} - ${base.name}` }
}

describe('jobSelectLabel', () => {
  it('renders number and name when bound', () => {
    expect(jobSelectLabel(97391, '[TEST] Job')).toBe('97391 - [TEST] Job')
  })

  it('renders the bare number when the name is missing', () => {
    expect(jobSelectLabel(97391, null)).toBe('97391')
  })

  it('renders empty while unbound', () => {
    expect(jobSelectLabel(null, null)).toBe('')
  })
})

describe('filterJobs', () => {
  const jobs = [
    job({ id: 'a', job_number: 100, name: 'Handrail', company_name: 'ABC' }),
    job({ id: 'b', job_number: 200, name: 'Gate', company_name: 'XYZ', status: 'in_progress' }),
    job({ id: 'c', job_number: 300, name: 'Fence', status: 'completed' }),
    job({ id: 'd', job_number: 400, name: 'Stairs', status: 'archived' }),
    job({ id: 'e', job_number: 500, name: 'Balustrade', status: 'rejected' }),
  ]

  it('keeps draft jobs — a fresh job must be assignable to a PO line', () => {
    expect(filterJobs(jobs, '').map((candidate) => candidate.id)).toEqual(['a', 'b'])
  })

  it('excludes completed, archived and rejected jobs', () => {
    for (const excluded of ['c', 'd', 'e']) {
      expect(filterJobs(jobs, '').some((candidate) => candidate.id === excluded)).toBe(false)
    }
  })

  it('matches on job number, name and company, case-insensitively', () => {
    expect(filterJobs(jobs, '200').map((candidate) => candidate.id)).toEqual(['b'])
    expect(filterJobs(jobs, 'handRAIL').map((candidate) => candidate.id)).toEqual(['a'])
    expect(filterJobs(jobs, 'xyz').map((candidate) => candidate.id)).toEqual(['b'])
  })

  it('returns nothing for a term matching no open job', () => {
    expect(filterJobs(jobs, 'fence')).toEqual([])
  })
})
