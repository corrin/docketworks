import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import type { UserProfile } from '@/api'

import { resolveSession, retryUnavailableSession, safeInternalRedirect } from './index'

const USER: UserProfile = {
  id: '11111111-1111-1111-1111-111111111111',
  username: 'staff@example.com',
  email: 'staff@example.com',
  first_name: 'Staff',
  last_name: 'Member',
  preferred_name: null,
  fullName: 'Staff Member',
  is_office_staff: true,
  is_superuser: false,
}

function failure(status: number): Error {
  return Object.assign(new Error('failed'), {
    isAxiosError: true,
    response: { status },
    toJSON: () => ({}),
  })
}

function networkFailure(code: string): Error {
  return Object.assign(new Error('offline'), {
    code,
    isAxiosError: true,
    toJSON: () => ({}),
  })
}

function queryClientResolving(): QueryClient {
  const client = new QueryClient()
  vi.spyOn(client, 'ensureQueryData').mockResolvedValue(USER)
  return client
}

function queryClientRejecting(error: Error): QueryClient {
  const client = new QueryClient()
  vi.spyOn(client, 'ensureQueryData').mockRejectedValue(error)
  return client
}

describe('session resolution', () => {
  it('keeps authenticated, unauthenticated, and unavailable states distinct', async () => {
    await expect(resolveSession(queryClientResolving())).resolves.toMatchObject({
      state: 'authenticated',
    })
    await expect(resolveSession(queryClientRejecting(failure(401)))).resolves.toEqual({
      state: 'unauthenticated',
    })

    const outage = failure(502)
    await expect(resolveSession(queryClientRejecting(outage))).resolves.toEqual({
      state: 'unavailable',
      error: outage,
    })
  })

  it('retries only two availability failures', () => {
    expect(retryUnavailableSession(0, failure(502))).toBe(true)
    expect(retryUnavailableSession(1, networkFailure('ERR_NETWORK'))).toBe(true)
    expect(retryUnavailableSession(2, failure(502))).toBe(false)
    expect(retryUnavailableSession(0, failure(500))).toBe(false)
    expect(retryUnavailableSession(0, failure(401))).toBe(false)
  })
})

describe('safeInternalRedirect', () => {
  it('accepts same-origin paths and rejects external or protocol-relative URLs', () => {
    expect(safeInternalRedirect('/')).toBe('/')
    expect(safeInternalRedirect('/jobs/1?tab=costs')).toBe('/jobs/1?tab=costs')
    expect(safeInternalRedirect('//attacker.example/path')).toBeUndefined()
    expect(safeInternalRedirect('https://attacker.example')).toBeUndefined()
    expect(safeInternalRedirect(undefined)).toBeUndefined()
  })

  it('rejects values that canonicalize to an external origin', () => {
    // Browsers treat backslashes as slashes when parsing URLs, so these
    // are protocol-relative external redirects in disguise.
    expect(safeInternalRedirect('/\\attacker.example')).toBeUndefined()
    expect(safeInternalRedirect('/\\/attacker.example/path')).toBeUndefined()
    expect(safeInternalRedirect('/%5Cattacker.example')).toBe('/%5Cattacker.example')
  })
})
