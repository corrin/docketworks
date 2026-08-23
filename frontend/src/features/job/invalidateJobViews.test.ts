import { QueryClient, type QueryKey } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { getFullJobOptions, jobJobsTimelineRetrieveQueryKey } from '@/api'

import { invalidateJobViews } from './invalidateJobViews'

const JOB_ID = '11111111-2222-3333-4444-555555555555'
const OTHER_JOB_ID = '99999999-8888-7777-6666-555555555555'

/**
 * The two keys as plain QueryKeys. Widened, not cast: the generated keys carry
 * a payload tag, and this test seeds a marker rather than a whole
 * JobDetailResponse — the assertion is about which entries were invalidated,
 * and the cached value is only there to make an entry exist.
 */
function jobViewKeys(jobId: string): { job: QueryKey; timeline: QueryKey } {
  const path = { job_id: jobId }
  return {
    job: getFullJobOptions({ path }).queryKey,
    timeline: jobJobsTimelineRetrieveQueryKey({ path }),
  }
}

function seed(client: QueryClient, jobId: string): { job: QueryKey; timeline: QueryKey } {
  const keys = jobViewKeys(jobId)
  client.setQueryData(keys.job, { seeded: true })
  client.setQueryData(keys.timeline, { seeded: true })
  return keys
}

describe('invalidateJobViews', () => {
  it('marks both of the job’s views stale', async () => {
    const client = new QueryClient()
    const keys = seed(client, JOB_ID)

    await invalidateJobViews(client, JOB_ID)

    expect(client.getQueryState(keys.job)?.isInvalidated).toBe(true)
    expect(client.getQueryState(keys.timeline)?.isInvalidated).toBe(true)
  })

  it('leaves another job’s views alone', async () => {
    const client = new QueryClient()
    seed(client, JOB_ID)
    const other = seed(client, OTHER_JOB_ID)

    await invalidateJobViews(client, JOB_ID)

    expect(client.getQueryState(other.job)?.isInvalidated).toBe(false)
    expect(client.getQueryState(other.timeline)?.isInvalidated).toBe(false)
  })
})
