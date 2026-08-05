/**
 * Transport configuration for the generated hey-api axios client:
 * - baseURL '' (the vite dev/preview proxy forwards /api to the backend)
 * - cookies on every request (auth cookies are HttpOnly, server-set)
 * - deep-trim of all outbound string fields
 * - ETag/If-Match optimistic-concurrency interceptors (ADR 0003)
 *
 * STUB: X-Session-Replay-Id attachment remains deferred until session replay
 * state is implemented.
 */
import {
  attachIfMatch,
  captureResourceVersion,
  handleConcurrencyFailure,
} from '@/lib/concurrency/interceptors'
import { trimStringsDeep } from '@/lib/sanitize'

import { client } from './generated/client.gen'

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
  return attachIfMatch(config)
})

client.instance.interceptors.response.use(
  (response) => captureResourceVersion(response),
  (error: unknown) => handleConcurrencyFailure(error),
)

export { client }
