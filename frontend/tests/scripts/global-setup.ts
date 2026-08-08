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

export default function globalSetup(): void {
  if (fs.existsSync(LOCK_FILE)) {
    const pid = fs.readFileSync(LOCK_FILE, 'utf8').trim()
    throw new Error(`E2E tests already running (PID: ${pid}). Kill it or delete ${LOCK_FILE}`)
  }
  fs.writeFileSync(LOCK_FILE, process.pid.toString())

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
          `A previous run left test data behind. Delete the '[TEST]'-prefixed rows ` +
          `(job_job, company_person, company_company) or restore the preserved backup ` +
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

    if (result.status !== 0) {
      throw new Error(`Database backup failed (exit code ${result.status}).`)
    }

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
