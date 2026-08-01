import { beforeEach, describe, expect, it } from 'vitest'

import { clearEtags, deleteEtag, etagKey, getEtag, setEtag } from '../etag-store'

describe('etag-store', () => {
  beforeEach(() => {
    clearEtags()
  })

  it('returns null for unknown keys', () => {
    expect(getEtag(etagKey('job', 'a1'))).toBeNull()
  })

  it('stores and retrieves an etag by resource key', () => {
    setEtag(etagKey('job', 'a1'), '"v1"')
    expect(getEtag(etagKey('job', 'a1'))).toBe('"v1"')
  })

  it('overwrites the previous etag for the same resource', () => {
    setEtag(etagKey('job', 'a1'), '"v1"')
    setEtag(etagKey('job', 'a1'), '"v2"')
    expect(getEtag(etagKey('job', 'a1'))).toBe('"v2"')
  })

  it('keys jobs and purchase orders independently even with equal ids', () => {
    setEtag(etagKey('job', 'same-id'), '"job-version"')
    setEtag(etagKey('po', 'same-id'), '"po-version"')
    expect(getEtag(etagKey('job', 'same-id'))).toBe('"job-version"')
    expect(getEtag(etagKey('po', 'same-id'))).toBe('"po-version"')
  })

  it('deletes a single etag', () => {
    setEtag(etagKey('po', 'p1'), '"v1"')
    deleteEtag(etagKey('po', 'p1'))
    expect(getEtag(etagKey('po', 'p1'))).toBeNull()
  })

  it('clears the whole store', () => {
    setEtag(etagKey('job', 'a1'), '"v1"')
    setEtag(etagKey('po', 'p1'), '"v2"')
    clearEtags()
    expect(getEtag(etagKey('job', 'a1'))).toBeNull()
    expect(getEtag(etagKey('po', 'p1'))).toBeNull()
  })
})
