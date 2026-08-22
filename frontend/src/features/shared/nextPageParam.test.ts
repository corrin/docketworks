import { describe, expect, it } from 'vitest'

import { nextPageParam } from './nextPageParam'

describe('nextPageParam', () => {
  it('advances until the last page, then stops', () => {
    expect(nextPageParam({ page: 1, total_pages: 3 })).toBe(2)
    expect(nextPageParam({ page: 3, total_pages: 3 })).toBeUndefined()
    expect(nextPageParam({ page: 1, total_pages: 0 })).toBeUndefined()
  })
})
