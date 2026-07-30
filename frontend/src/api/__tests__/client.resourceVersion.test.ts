import { describe, expect, it } from 'vitest'
import { strongResourceVersion } from '@/api/client'

describe('strongResourceVersion', () => {
  it('prefers the strong resource-version header over a weak response ETag', () => {
    expect(
      strongResourceVersion({
        'x-resource-version': '"job:123:strong"',
        etag: 'W/"compressed"',
      }),
    ).toBe('"job:123:strong"')
  })

  it('falls back to a strong ETag', () => {
    expect(strongResourceVersion({ etag: '"po:456:strong"' })).toBe('"po:456:strong"')
  })

  it('ignores a weak-only ETag', () => {
    expect(strongResourceVersion({ etag: 'W/"compressed"' })).toBeNull()
  })
})
