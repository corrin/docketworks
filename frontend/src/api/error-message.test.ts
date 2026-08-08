import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { isApiErrorStatus } from './error-message'

describe('isApiErrorStatus', () => {
  it('matches only axios responses with the requested status', () => {
    const unauthorized = new AxiosError('unauthorized', 'ERR_BAD_REQUEST', undefined, undefined, {
      data: {},
      status: 401,
      statusText: 'Unauthorized',
      headers: {},
      config: { headers: new AxiosHeaders() },
    })

    expect(isApiErrorStatus(unauthorized, 401)).toBe(true)
    expect(isApiErrorStatus(unauthorized, 500)).toBe(false)
    expect(isApiErrorStatus(new Error('offline'), 401)).toBe(false)
  })
})
