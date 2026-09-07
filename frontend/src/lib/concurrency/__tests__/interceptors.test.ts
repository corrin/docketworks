import { beforeEach, describe, expect, it } from 'vitest'

import { attachIfMatch, captureResourceVersion } from '../interceptors'
import { clearEtags, etagKey, getEtag, setEtag } from '../etag-store'

const PO_ID = '22222222-2222-2222-2222-222222222222'
const COUNT_ID = '33333333-3333-3333-3333-333333333333'

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

  it('stores a correction token against the returned count, preserving the original token', () => {
    const original = `"stocktake:${PO_ID}:2"`
    const correction = `"stocktake:${COUNT_ID}:0"`
    setEtag(etagKey('stocktake', PO_ID), original)
    captureResourceVersion({
      headers: { etag: `W/${correction}`, 'x-resource-version': correction },
      config: { url: `/api/purchasing/stocktakes/${PO_ID}/correct/` },
    })
    expect(getEtag(etagKey('stocktake', PO_ID))).toBe(original)
    expect(getEtag(etagKey('stocktake', COUNT_ID))).toBe(correction)
  })

  it('stores the version a PO read returns', () => {
    captureResourceVersion({
      headers: { etag: `"po:${PO_ID}:1"` },
      config: { url: `/api/purchasing/purchase-orders/${PO_ID}/` },
    })

    expect(getEtag(etagKey('po', PO_ID))).toBe(`"po:${PO_ID}:1"`)
  })

  it('stores the version a delivery receipt returns, reading the id from the body', () => {
    // The receipt POST addresses its PO through the body, so without the
    // body fallback the fresh ETag is dropped and the next PO mutation 412s.
    captureResourceVersion({
      headers: { etag: `"po:${PO_ID}:2"` },
      config: {
        url: '/api/purchasing/delivery-receipts/',
        data: JSON.stringify({ purchase_order_id: PO_ID, allocations: {} }),
      },
    })

    expect(getEtag(etagKey('po', PO_ID))).toBe(`"po:${PO_ID}:2"`)
  })

  it('ignores a weak validator', () => {
    captureResourceVersion({
      headers: { etag: 'W/"po-weak"' },
      config: { url: `/api/purchasing/purchase-orders/${PO_ID}/` },
    })

    expect(getEtag(etagKey('po', PO_ID))).toBeNull()
  })
})
