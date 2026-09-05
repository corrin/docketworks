import { beforeEach, describe, expect, it } from 'vitest'

import { attachIfMatch, captureResourceVersion } from '../interceptors'
import { clearEtags, etagKey, getEtag, setEtag } from '../etag-store'

const PO_ID = '22222222-2222-2222-2222-222222222222'

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

describe('captureResourceVersion', () => {
  beforeEach(clearEtags)

  it('stores the version a PO read returns', () => {
    captureResourceVersion({
      headers: { etag: '"po-v1"' },
      config: { url: `/api/purchasing/purchase-orders/${PO_ID}/` },
    })

    expect(getEtag(etagKey('po', PO_ID))).toBe('"po-v1"')
  })

  it('stores the version a delivery receipt returns, reading the id from the body', () => {
    // The receipt POST addresses its PO through the body, so without the
    // body fallback the fresh ETag is dropped and the next PO mutation 412s.
    captureResourceVersion({
      headers: { etag: '"po-v2"' },
      config: {
        url: '/api/purchasing/delivery-receipts/',
        data: JSON.stringify({ purchase_order_id: PO_ID, allocations: {} }),
      },
    })

    expect(getEtag(etagKey('po', PO_ID))).toBe('"po-v2"')
  })

  it('ignores a weak validator', () => {
    captureResourceVersion({
      headers: { etag: 'W/"po-weak"' },
      config: { url: `/api/purchasing/purchase-orders/${PO_ID}/` },
    })

    expect(getEtag(etagKey('po', PO_ID))).toBeNull()
  })
})
