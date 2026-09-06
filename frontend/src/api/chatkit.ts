import { getSessionReplayId } from '@/features/shared/session-replay/replayId'

import { refreshAccessToken } from './client'
import { hardNavigateToChangePassword } from './password-gate'
import { zAuthErrorOut } from './generated/zod.gen'

export function quotingChatUrl(jobId: string): string {
  return `/api/job/jobs/${encodeURIComponent(jobId)}/quote-chat/`
}

/** GPT: ChatKit owns its streaming protocol; session recovery remains application-owned. */
export function quotingChatFetch(jobId: string, csrfToken: string): typeof fetch {
  const endpoint = new URL(quotingChatUrl(jobId), window.location.origin)
  return async (input, init) => {
    const request = new Request(input, init)
    if (request.url !== endpoint.href) {
      throw new Error('Quoting chat requested an unexpected endpoint')
    }
    const headers = new Headers(request.headers)
    headers.set('X-CSRFToken', csrfToken)
    const replayId = getSessionReplayId()
    if (replayId) headers.set('X-Session-Replay-Id', replayId)
    const authenticated = new Request(request, { headers, credentials: 'same-origin' })
    const response = await fetch(authenticated.clone())
    if (
      (response.status === 401 || response.status === 403) &&
      !response.headers.get('Content-Type')?.includes('application/json')
    )
      return response
    if (response.status === 403) {
      const body: unknown = await response.clone().json()
      if (
        typeof body === 'object' &&
        body !== null &&
        'code' in body &&
        body.code === 'password_change_required'
      ) {
        hardNavigateToChangePassword()
      }
      return response
    }
    if (response.status !== 401) return response
    const body: unknown = await response.clone().json()
    const error = zAuthErrorOut.safeParse(body)
    if (!error.success || error.data.code !== 'authentication_required') return response
    authenticated.signal.throwIfAborted()
    await refreshAccessToken()
    authenticated.signal.throwIfAborted()
    return fetch(authenticated)
  }
}
