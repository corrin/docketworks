import { create, AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { installPasswordGate } from './password-gate'

function response(
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown,
): AxiosResponse {
  return { config, data, headers: {}, status, statusText: String(status) }
}

function rejection(config: InternalAxiosRequestConfig, status: number, data: unknown): AxiosError {
  return new AxiosError(
    'refused',
    'ERR_BAD_REQUEST',
    config,
    undefined,
    response(config, status, data),
  )
}

function instanceRejectingWith(status: number, data: unknown) {
  return create({
    adapter: async (config) => {
      throw rejection(config, status, data)
    },
  })
}

describe('password gate', () => {
  it('navigates on the typed 403 and still rethrows', async () => {
    const instance = instanceRejectingWith(403, {
      detail: 'Password change required.',
      code: 'password_change_required',
      error_id: null,
    })
    const navigate = vi.fn()
    installPasswordGate(instance, navigate)

    await expect(instance.get('/api/accounts/staff/all/')).rejects.toThrow()
    expect(navigate).toHaveBeenCalledOnce()
  })

  it('ignores a plain 403', async () => {
    const instance = instanceRejectingWith(403, {
      detail: 'You do not have permission to perform this action.',
      error_id: null,
    })
    const navigate = vi.fn()
    installPasswordGate(instance, navigate)

    await expect(instance.get('/api/accounts/staff/')).rejects.toThrow()
    expect(navigate).not.toHaveBeenCalled()
  })

  it('ignores other statuses carrying the code shape', async () => {
    const instance = instanceRejectingWith(401, { code: 'password_change_required' })
    const navigate = vi.fn()
    installPasswordGate(instance, navigate)

    await expect(instance.get('/api/accounts/me/')).rejects.toThrow()
    expect(navigate).not.toHaveBeenCalled()
  })
})
