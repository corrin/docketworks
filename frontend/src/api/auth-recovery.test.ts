import { create, AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { installAuthRecovery } from './auth-recovery'

function response(
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown,
): AxiosResponse {
  return { config, data, headers: {}, status, statusText: String(status) }
}

function rejection(
  config: InternalAxiosRequestConfig,
  data: unknown = { code: 'authentication_required' },
): AxiosError {
  return new AxiosError(
    'unauthorized',
    'ERR_BAD_REQUEST',
    config,
    undefined,
    response(config, 401, data),
  )
}

describe('auth recovery', () => {
  it('refreshes and replays an authentication challenge exactly once', async () => {
    let attempts = 0
    const instance = create({
      adapter: async (config) => {
        attempts += 1
        if (attempts === 1) throw rejection(config)
        return response(config, 200, { ok: true })
      },
    })
    const refresh = vi.fn(async () => undefined)
    installAuthRecovery(instance, refresh)

    const result = await instance.post('/api/jobs/', { name: 'Test' })

    expect(result.data).toEqual({ ok: true })
    expect(refresh).toHaveBeenCalledOnce()
    expect(attempts).toBe(2)
  })

  it('shares one refresh across simultaneous challenges', async () => {
    const attempts = new Map<string, number>()
    let releaseRefresh: (() => void) | undefined
    const refresh = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          releaseRefresh = resolve
        }),
    )
    const instance = create({
      adapter: async (config) => {
        const url = config.url ?? ''
        const count = (attempts.get(url) ?? 0) + 1
        attempts.set(url, count)
        if (count === 1) throw rejection(config)
        return response(config, 200, { url })
      },
    })
    installAuthRecovery(instance, refresh)

    const first = instance.get('/api/one/')
    const second = instance.get('/api/two/')
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    releaseRefresh?.()

    await expect(Promise.all([first, second])).resolves.toHaveLength(2)
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('returns the original challenge when refresh fails', async () => {
    const original = new AxiosError('placeholder')
    const instance = create({
      adapter: async (config) => {
        const failure = rejection(config)
        Object.assign(original, failure)
        throw original
      },
    })
    installAuthRecovery(instance, async () => {
      throw new Error('refresh failed')
    })

    await expect(instance.get('/api/private/')).rejects.toBe(original)
  })

  it('does not refresh domain 401s or auth endpoints', async () => {
    const refresh = vi.fn(async () => undefined)
    const instance = create({
      adapter: async (config) => {
        if (config.url === '/api/company/provider/') {
          throw rejection(config, { detail: 'Xero authentication required' })
        }
        throw rejection(config)
      },
    })
    installAuthRecovery(instance, refresh)

    await expect(instance.get('/api/company/provider/')).rejects.toBeInstanceOf(AxiosError)
    await expect(instance.post('/api/accounts/token/refresh/')).rejects.toBeInstanceOf(AxiosError)
    await expect(
      instance.post('https://staff.example/api/accounts/token/refresh/?source=client'),
    ).rejects.toBeInstanceOf(AxiosError)
    expect(refresh).not.toHaveBeenCalled()
  })

  it('does not replay a request aborted while refresh is pending', async () => {
    let releaseRefresh: (() => void) | undefined
    let attempts = 0
    const instance = create({
      adapter: async (config) => {
        attempts += 1
        throw rejection(config)
      },
    })
    installAuthRecovery(
      instance,
      () =>
        new Promise<void>((resolve) => {
          releaseRefresh = resolve
        }),
    )
    const controller = new AbortController()

    const request = instance.get('/api/private/', { signal: controller.signal })
    await vi.waitFor(() => expect(releaseRefresh).toBeTypeOf('function'))
    controller.abort()
    releaseRefresh?.()

    // Cancellation must surface as cancellation — not as the original 401,
    // which callers would misread as an authentication failure.
    await expect(request).rejects.toMatchObject({ code: 'ERR_CANCELED' })
    expect(attempts).toBe(1)
  })
})
