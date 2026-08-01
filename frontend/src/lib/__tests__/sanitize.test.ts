import { describe, expect, it } from 'vitest'

import { trimStringsDeep } from '../sanitize'

describe('trimStringsDeep', () => {
  it('trims nested string fields', () => {
    expect(trimStringsDeep({ a: '  x ', b: { c: ' y' }, d: [' z '] })).toEqual({
      a: 'x',
      b: { c: 'y' },
      d: ['z'],
    })
  })

  it('leaves numbers, booleans and null untouched', () => {
    expect(trimStringsDeep({ n: 1, b: false, z: null })).toEqual({ n: 1, b: false, z: null })
  })

  it('strips undefined values', () => {
    expect(trimStringsDeep({ a: 'x', gone: undefined })).toEqual({ a: 'x' })
  })

  it('never trims secret-bearing keys (passwords are sent byte-for-byte)', () => {
    const payload = {
      username: '  jo@example.com ',
      password: '  hunter2 ',
      new_password: ' a b ',
      current_password: ' c ',
      refresh: ' tok ',
    }
    expect(trimStringsDeep(payload)).toEqual({
      username: 'jo@example.com',
      password: '  hunter2 ',
      new_password: ' a b ',
      current_password: ' c ',
      refresh: ' tok ',
    })
  })
})
