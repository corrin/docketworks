import { describe, expect, it } from 'vitest'

import { phoneCallQueryFor, QUEUE_META } from './phoneCallFilters'

describe('phoneCallQueryFor', () => {
  const defaults = { direction: 'all', recordingsOnly: false, q: '' } as const

  it('asks the unmatched queue for calls with no company', () => {
    expect(phoneCallQueryFor({ tab: 'unmatched', ...defaults })).toEqual({
      company_match: 'unmatched',
    })
  })

  it('asks the unlinked queue for matched calls with no job', () => {
    expect(phoneCallQueryFor({ tab: 'unlinked', ...defaults })).toEqual({
      company_match: 'matched',
      job_link: 'unlinked',
    })
  })

  it('asks the recent and all queues for everything', () => {
    const everything = { company_match: 'all', job_link: 'all' }
    expect(phoneCallQueryFor({ tab: 'recent', ...defaults })).toEqual(everything)
    expect(phoneCallQueryFor({ tab: 'all', ...defaults })).toEqual(everything)
  })

  it('omits the filters left at their defaults', () => {
    const query = phoneCallQueryFor({
      tab: 'all',
      direction: 'all',
      recordingsOnly: false,
      q: '  ',
    })
    expect(query).not.toHaveProperty('direction')
    expect(query).not.toHaveProperty('has_recording')
    expect(query).not.toHaveProperty('q')
  })

  it('sends the filters the user has actually set, search trimmed', () => {
    expect(
      phoneCallQueryFor({ tab: 'all', direction: 'inbound', recordingsOnly: true, q: '  021  ' }),
    ).toEqual({
      company_match: 'all',
      job_link: 'all',
      direction: 'inbound',
      has_recording: true,
      q: '021',
    })
  })

  it('never carries a page: the infinite query owns that parameter', () => {
    // Fable: a `page` in the base query would be merged over by the page param
    // the generated queryFn injects on page one and disagree with it after.
    expect(
      phoneCallQueryFor({ tab: 'recent', direction: 'inbound', recordingsOnly: true, q: 'x' }),
    ).not.toHaveProperty('page')
  })
})

describe('QUEUE_META', () => {
  it('titles and describes every tab', () => {
    expect(QUEUE_META.recent.title).toBe('Recent Calls')
    expect(QUEUE_META.unmatched.title).toBe('Unmatched Calls')
    expect(QUEUE_META.unlinked.title).toBe('Matched Calls Needing Job Link')
    expect(QUEUE_META.all.title).toBe('All Calls')
    for (const meta of Object.values(QUEUE_META)) {
      expect(meta.description).not.toBe('')
    }
  })
})
