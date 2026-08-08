/**
 * SEAM — XERO LIFECYCLE NOT PORTED. v1's global setup also ran a Xero ping
 * preflight (connected? production client? XERO_READONLY?) and opened a
 * per-run Xero sync window that teardown closed; teardown additionally saved
 * and re-injected the active Xero app token around the restore and waited 90s
 * for in-flight Celery/Xero work to settle. All of that must return before any
 * Xero-touching spec ports (9 of v1's 40 specs touch a live tenant). Blocked
 * on v2 lacking the xero_ping operation and the e2e_artifacts sync-window
 * reader. See v1 frontend/tests/scripts/{global-setup,global-teardown,
 * e2e-sync-windows}.ts for the reference implementation.
 */
import { spawnSync } from 'child_process'
import fs from 'fs'
import os from 'os'
import path from 'path'
import { checkSafeToTest, getBackupsDir, getDbConfig, syncSequences } from './db-backup-utils'
import { assertSpawnSucceeded } from './process-result'

const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

/**
 * Identifier for this run. Currently only recorded in the lock file (line 3,
 * the position v1's teardown reads it from) so the lock format survives the
 * Xero port unchanged — the sync window it will label is not ported yet.
 */
function mintRunId(): string {
  return Math.random().toString(36).substring(2, 10)
}

const pad = (value: number) => value.toString().padStart(2, '0')

function formatTimestamp(date: Date): string {
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`
}

/** Acquire the run lock atomically so concurrent setup processes cannot both pass preflight. */
export function acquireE2ELock(lockFile: string, pid: number): void {
  try {
    fs.writeFileSync(lockFile, pid.toString(), { encoding: 'utf8', flag: 'wx' })
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'EEXIST') {
      const owner = fs.readFileSync(lockFile, 'utf8').split('\n')[0]?.trim() || 'unknown'
      throw new Error(`E2E tests already running (PID: ${owner}). Kill it or delete ${lockFile}`, {
        cause: error,
      })
    }
    throw error
  }
}

export default function globalSetup(): void {
  acquireE2ELock(LOCK_FILE, process.pid)

  // Playwright skips globalTeardown when globalSetup throws, so any failure
  // past this point must clean up the lock (and any partial dump) here —
  // otherwise the next run refuses to start for a dead PID.
  let backupFile: string | null = null
  try {
    // All checks are read-only — they abort if something is wrong, never fix it.
    console.log('[db] Checking database is safe for E2E tests...')
    const dbConfig = getDbConfig()
    const dbCheck = checkSafeToTest(dbConfig)

    if (dbCheck.issues.length > 0) {
      const issueList = dbCheck.issues.map((i) => `  - ${i}`).join('\n')
      throw new Error(
        `E2E pre-flight checks failed:\n${issueList}\n\n` +
          `A previous run left test data behind. Run 'npm run test:e2e:reset -- --confirm' ` +
          `to remove it (dry run without --confirm), or restore the preserved backup ` +
          `under restore/e2e/, then rerun.`,
      )
    }
    console.log('[db] Database is clean.')

    // Sync sequences as a safety net (idempotent, fast)
    console.log('[db] Syncing sequences...')
    syncSequences()
    console.log('[db] Sequences synced.')

    const runId = mintRunId()

    // Take backup
    console.log('[db] Backing up database before tests...')
    const backupDir = getBackupsDir()
    fs.mkdirSync(backupDir, { recursive: true })

    backupFile = path.join(backupDir, `backup_${formatTimestamp(new Date())}.sql`)
    const outputFd = fs.openSync(backupFile, 'w')

    // --clean + --if-exists produce a dump whose DROP statements are safe to
    // replay into a populated schema (IF EXISTS suppresses "object does not
    // exist" errors). Paired with ON_ERROR_STOP + --single-transaction on
    // restore, any real failure aborts the whole transaction so the DB is
    // either fully restored or untouched — never partial.
    const dumpArgs = ['--clean', '--if-exists', '-h', dbConfig.host]
    if (dbConfig.port) {
      dumpArgs.push('-p', dbConfig.port)
    }
    dumpArgs.push('-U', dbConfig.user, dbConfig.database)
    const result = spawnSync('pg_dump', dumpArgs, {
      stdio: ['ignore', outputFd, 'inherit'],
      env: { ...process.env, PGPASSWORD: dbConfig.password },
    })

    fs.closeSync(outputFd)

    assertSpawnSucceeded('Database backup', result)

    // Record backup path in the lock file (line 2) so teardown knows a backup
    // was taken in this run and where to find it, then the run id (line 3).
    // Order matters: teardown reads the backup path positionally.
    fs.appendFileSync(LOCK_FILE, `\n${backupFile}\n${runId}`, 'utf8')

    console.log(`[db] Backup complete: ${backupFile}`)
  } catch (error) {
    fs.rmSync(LOCK_FILE, { force: true })
    if (backupFile) {
      // Setup failed before the backup was recorded as complete, so anything
      // on disk is a partial dump — worthless for restore and unsafe to keep.
      fs.rmSync(backupFile, { force: true })
    }
    throw error
  }
}
