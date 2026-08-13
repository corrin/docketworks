import { beforeEach, describe, expect, it } from 'vitest'

import { attachIfMatch } from '../interceptors'
import { clearEtags, etagKey, setEtag } from '../etag-store'

describe('attachIfMatch', () => {
  beforeEach(clearEtags)

  it('preserves the original precondition when a request is replayed', () => {
    const jobId = '11111111-1111-1111-1111-111111111111'
    setEtag(etagKey('job', jobId), '"newer"')
    const config = {
      url: `/api/job/jobs/${jobId}/`,
      method: 'patch',
      data: {},
      headers: { 'If-Match': '"original"' },
    }

    attachIfMatch(config)

    expect(config.headers['If-Match']).toBe('"original"')
  })
})
