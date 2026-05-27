let sessionReplayId: string | null = null

export function getSessionReplayId(): string | null {
  return sessionReplayId
}

export function setSessionReplayId(value: string | null): void {
  sessionReplayId = value
}
