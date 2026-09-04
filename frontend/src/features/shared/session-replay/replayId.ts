/**
 * The current recording's id, shared between the capture service and the
 * axios interceptor that stamps X-Session-Replay-Id onto every request.
 *
 * Its own module purely to break the import cycle: the interceptor lives in
 * api/client.ts, and the capture service calls the generated SDK, which is
 * configured by that same client.
 */
let sessionReplayId: string | null = null

export function getSessionReplayId(): string | null {
  return sessionReplayId
}

export function setSessionReplayId(value: string | null): void {
  sessionReplayId = value
}
