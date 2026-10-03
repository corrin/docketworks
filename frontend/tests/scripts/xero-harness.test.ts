import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ files: new Map<string, string>() }))
vi.mock('fs', () => ({
  default: {
    writeFileSync: (file: string, text: string) => {
      state.files.set(file, text)
    },
    rmSync: (file: string) => {
      state.files.delete(file)
    },
  },
}))
vi.mock('./db-backup-utils', () => ({ getApplicationUrl: () => 'https://app.invalid' }))
vi.mock('./global-teardown', () => ({
  beginFakeTokenSnapshot: vi.fn(() => '/private/token.json'),
  finishFakeTokenSnapshot: vi.fn(),
}))
vi.mock('./xero-login', () => ({ ensureXeroConnected: vi.fn() }))
import globalSetup, { checkXeroStatus } from './global-setup'
import { ensureXeroConnected } from './xero-login'
import { finishFakeTokenSnapshot } from './global-teardown'
import { configureXeroMode, recordedXeroMode } from './xero-mode'

beforeEach(() => {
  state.files.clear()
  vi.stubEnv('E2E_TEST_USERNAME', 'test')
  vi.stubEnv('E2E_TEST_PASSWORD', 'test')
  vi.stubEnv('XERO_USERNAME', 'test')
  vi.stubEnv('XERO_PASSWORD', 'test')
  vi.stubEnv('E2E_XERO_MODE', 'fake')
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

function login(): Response {
  return new Response('{}', { headers: { 'set-cookie': 'access_token=test; Path=/' } })
}

describe('E2E transport safety', () => {
  it('overrides inherited application settings and refuses missing or conflicting cleanup metadata', () => {
    const env: NodeJS.ProcessEnv = { XERO_FAKE: 'false' }
    expect(configureXeroMode(env)).toBe('fake')
    expect(env.XERO_FAKE).toBe('true')
    expect(() => recordedXeroMode('1\nbackup\nrun')).toThrow('no valid Xero mode')
    expect(() => recordedXeroMode('1\nbackup\nrun\nreal')).toThrow('disagrees')
    expect(recordedXeroMode('1\nbackup\nrun\nfake')).toBe('fake')
    expect(() => configureXeroMode({ E2E_XERO_MODE: 'typo' })).toThrow('Invalid')
  })

  it('sends expected mode with ping and treats mismatch as terminal before OAuth', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(login())
      .mockResolvedValueOnce(new Response('{}', { status: 409 }))
    vi.stubGlobal('fetch', fetch)
    await expect(globalSetup()).rejects.toThrow('mode disagrees')
    expect(fetch.mock.calls[1]?.[0]).toBe('https://app.invalid/api/xero/ping/?expected_fake=true')
    expect(ensureXeroConnected).not.toHaveBeenCalled()
    expect(finishFakeTokenSnapshot).toHaveBeenCalledWith('/private/token.json')
    expect(state.files.size).toBe(0)
  })

  it('never starts live OAuth after a failed fake connection', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(login())
        .mockResolvedValueOnce(new Response('{}', { status: 500 })),
    )
    await expect(globalSetup()).rejects.toThrow('Fix the local fake seed/connection')
    expect(ensureXeroConnected).not.toHaveBeenCalled()
    expect(finishFakeTokenSnapshot).toHaveBeenCalledWith('/private/token.json')
  })

  it('allows OAuth recovery only for an explicitly live run', async () => {
    vi.stubEnv('E2E_XERO_MODE', 'real')
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(login())
      .mockResolvedValueOnce(new Response('{}', { status: 500 }))
      .mockResolvedValueOnce(login())
      .mockResolvedValueOnce(new Response('{}', { status: 500 }))
    vi.stubGlobal('fetch', fetch)
    await expect(globalSetup()).rejects.toThrow('Complete the OAuth flow')
    expect(ensureXeroConnected).toHaveBeenCalledOnce()
    expect(fetch.mock.calls[1]?.[0]).toContain('expected_fake=false')
    expect(fetch.mock.calls[3]?.[0]).toContain('expected_fake=false')
  })

  it('rejects a live mode mismatch without reconnecting', async () => {
    vi.stubEnv('E2E_XERO_MODE', 'real')
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(login())
        .mockResolvedValueOnce(new Response('{}', { status: 409 })),
    )
    await expect(checkXeroStatus()).rejects.toThrow('mode disagrees')
    expect(ensureXeroConnected).not.toHaveBeenCalled()
  })
})
