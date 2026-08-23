import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { seedJobViews } from '@/test/jobViews'

import { invalidateJobViews } from './invalidateJobViews'

const JOB_ID = '11111111-2222-3333-4444-555555555555'
const OTHER_JOB_ID = '99999999-8888-7777-6666-555555555555'

describe('invalidateJobViews', () => {
  it('marks both of the job’s views stale', async () => {
    const client = new QueryClient()
    const keys = seedJobViews(client, JOB_ID)

    await invalidateJobViews(client, JOB_ID)

    expect(client.getQueryState(keys.job)?.isInvalidated).toBe(true)
    expect(client.getQueryState(keys.timeline)?.isInvalidated).toBe(true)
  })

  it('leaves another job’s views alone', async () => {
    const client = new QueryClient()
    seedJobViews(client, JOB_ID)
    const other = seedJobViews(client, OTHER_JOB_ID)

    await invalidateJobViews(client, JOB_ID)

    expect(client.getQueryState(other.job)?.isInvalidated).toBe(false)
    expect(client.getQueryState(other.timeline)?.isInvalidated).toBe(false)
  })
})
