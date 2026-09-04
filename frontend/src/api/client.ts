/**
 * Transport configuration for the generated hey-api axios client:
 * - baseURL '' (the vite dev/preview proxy forwards /api to the backend)
 * - cookies on every request (auth cookies are HttpOnly, server-set)
 * - deep-trim of all outbound string fields
 * - ETag/If-Match optimistic-concurrency interceptors (ADR 0003)
 * - X-Session-Replay-Id, which links a request (and any error it persists)
 *   back to the recording of the session that made it
 */
import {
  attachIfMatch,
  captureResourceVersion,
  handleConcurrencyFailure,
} from '@/lib/concurrency/interceptors'
import { getSessionReplayId } from '@/features/shared/session-replay/replayId'
import { trimStringsDeep } from '@/lib/sanitize'

import { installAuthRecovery } from './auth-recovery'
import { client } from './generated/client.gen'
import { installPasswordGate } from './password-gate'
import { accountsTokenRefreshCreate } from './generated/sdk.gen'

client.setConfig({
  baseURL: '',
  timeout: 60_000,
  withCredentials: true,
})

client.instance.interceptors.request.use((config) => {
  // Normalize outbound payloads so every string field is trimmed before hitting the API
  if (config.data !== undefined) {
    config.data = trimStringsDeep(config.data)
  }
  if (config.params !== undefined) {
    config.params = trimStringsDeep(config.params)
  }
  const sessionReplayId = getSessionReplayId()
  if (sessionReplayId) {
    config.headers['X-Session-Replay-Id'] = sessionReplayId
  }
  return attachIfMatch(config)
})

client.instance.interceptors.response.use(
  (response) => captureResourceVersion(response),
  (error: unknown) => handleConcurrencyFailure(error),
)

installAuthRecovery(client.instance, async () => {
  await accountsTokenRefreshCreate({ body: {}, throwOnError: true })
})

installPasswordGate(client.instance)

export { client }
