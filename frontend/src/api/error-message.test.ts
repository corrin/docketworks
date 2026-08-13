import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import {
  isApiErrorStatus,
  isAvailabilityError,
  isSessionAuthenticationError,
} from './error-message'

function failure(status: number, data: unknown): AxiosError {
  return new AxiosError('failed', 'ERR_BAD_RESPONSE', undefined, undefined, {
    data,
    status,
    statusText: 'failed',
    headers: {},
    config: { headers: new AxiosHeaders() },
  })
}

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

describe('authentication and availability classification', () => {
  it('distinguishes app-session challenges from domain 401s', () => {
    expect(isSessionAuthenticationError(failure(401, { code: 'authentication_required' }))).toBe(
      true,
    )
    expect(isSessionAuthenticationError(failure(401, { detail: 'Xero auth required' }))).toBe(false)
  })

  it('classifies only network and gateway availability failures', () => {
    expect(isAvailabilityError(new AxiosError('offline', 'ERR_NETWORK'))).toBe(true)
    expect(isAvailabilityError(failure(502, {}))).toBe(true)
    expect(isAvailabilityError(failure(500, {}))).toBe(false)
    expect(isAvailabilityError(new AxiosError('cancelled', 'ERR_CANCELED'))).toBe(false)
  })
})
