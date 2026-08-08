import * as fs from 'fs'
import os from 'os'
import path from 'path'

/**
 * Records the wall-clock span of each E2E run, so the backend Xero sync can
 * ignore the contacts, invoices and quotes the run created in Xero.
 *
 * E2E writes to a live Xero org, and those objects outlive the database
 * restore that teardown performs. The hourly Xero poll would otherwise replay
 * them into the clean database an hour later.
 *
 * Deliberately a file, not a database table: teardown restores the database
 * from a backup taken before the run, so nothing written to the database
 * during a run can describe that run afterwards. Fixed path in the system temp
 * dir, same convention as the E2E lock file, so the backend agrees on it
 * without being told.
 *
 * Read by apps/xero/e2e_artifacts.py.
 */
const WINDOWS_FILE = path.join(os.tmpdir(), 'docketworks-e2e-sync-windows.json')

type SyncWindow = {
  run_id: string
  started_at: string
  ended_at: string | null
}

function isSyncWindow(value: unknown): value is SyncWindow {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const entry: Record<string, unknown> = { ...value }
  return (
    typeof entry.run_id === 'string' &&
    typeof entry.started_at === 'string' &&
    (entry.ended_at === null || typeof entry.ended_at === 'string')
  )
}

function read(): SyncWindow[] {
  if (!fs.existsSync(WINDOWS_FILE)) {
    return []
  }
  const parsed: unknown = JSON.parse(fs.readFileSync(WINDOWS_FILE, 'utf8'))
  if (!Array.isArray(parsed) || !parsed.every(isSyncWindow)) {
    throw new Error(`${WINDOWS_FILE} does not contain a valid sync-window array`)
  }
  return parsed
}

function write(windows: SyncWindow[]): void {
  fs.mkdirSync(path.dirname(WINDOWS_FILE), { recursive: true })
  fs.writeFileSync(WINDOWS_FILE, JSON.stringify(windows, null, 2), 'utf8')
}

/**
 * Open this run's window. Left open for the whole run: while tests execute,
 * inbound Xero data must behave exactly as it does in production, because that
 * round trip is what the run exercises. Only closed windows suppress.
 */
export function openSyncWindow(runId: string): void {
  const windows = read()
  windows.push({ run_id: runId, started_at: new Date().toISOString(), ended_at: null })
  write(windows)
}

/**
 * Close this run's window, making everything it created in Xero inert.
 *
 * A run with no recorded window is reported, not raised: the requested end
 * state — no window left open for this run — already holds, and this runs
 * inside teardown, where throwing would strand the lock file and block every
 * later run. The warning is the useful part, because it means that run's Xero
 * artifacts were never covered by a window and can still be replayed.
 */
export function closeSyncWindow(runId: string): void {
  let windows: SyncWindow[]
  try {
    windows = read()
  } catch (error) {
    // Teardown must not throw here (it would strand the lock file); the
    // warning tells the operator the run's artifacts are unprotected.
    const reason = error instanceof Error ? error.message : String(error)
    console.warn(
      `[e2e] Could not read ${WINDOWS_FILE} (${reason}); ` +
        `sync window for run ${runId} left open and its Xero artifacts unprotected.`,
    )
    return
  }
  const window = windows.find((w) => w.run_id === runId)
  if (!window) {
    console.warn(
      `[e2e] No sync window recorded for run ${runId} in ${WINDOWS_FILE}. ` +
        `Nothing to close, but this run's Xero artifacts are unprotected and ` +
        `the hourly poll may replay them into the restored database.`,
    )
    return
  }
  window.ended_at = new Date().toISOString()
  write(windows)
}

export { WINDOWS_FILE }
