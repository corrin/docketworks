import type { SpawnSyncReturns } from 'node:child_process'

function outputText(output: Buffer | string | null | undefined): string {
  return output?.toString().trim() ?? ''
}

/** Fail a synchronous child process with enough context to diagnose startup and signal failures. */
export function assertSpawnSucceeded(
  context: string,
  result: Pick<SpawnSyncReturns<Buffer | string>, 'error' | 'signal' | 'status' | 'stderr'>,
): void {
  if (result.status === 0 && result.error === undefined) return

  const details = [
    result.error ? `could not start: ${result.error.message}` : null,
    result.status !== null ? `exit code ${result.status}` : null,
    result.signal !== null ? `signal ${result.signal}` : null,
    outputText(result.stderr) ? `stderr: ${outputText(result.stderr)}` : null,
  ].filter((detail): detail is string => detail !== null)

  throw new Error(`${context} failed (${details.join('; ') || 'unknown process failure'})`)
}
