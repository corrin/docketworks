import { recordedXeroMode, xeroMode as selectedXeroMode } from './xero-mode'
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import os from 'os'
import path from 'path'
import {
  checkSafeToTest,
  getDbConfig,
  getBackupsDir,
  runIntegrityCheck,
  runPsql,
  syncSequences,
  type DbConfig,
} from './db-backup-utils'
import { runStateDir } from './history-sources'
import { runE2ECleanup } from './e2e-cleanup'
import { closeSyncWindow } from './e2e-sync-windows'
import { assertSpawnSucceeded } from './process-result'

const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

// Let in-flight Celery/Xero work finish against the dirty test DB before the
// restore replaces it — a queued webhook/full-sync task can otherwise recreate
// [TEST] rows in the clean DB seconds after restore. Ported at v1's value even
// though slice 1 has no async Xero work yet; slice 2's sync engine relies on it.
const PRE_RESTORE_XERO_SETTLE_MS = 90_000

// A summary-PDF batch is about three seconds and a warm shutdown lets one
// finish; anything still running after this is not going to stop by itself.
const CELERY_EXIT_WAIT_MS = 120_000
const CELERY_EXIT_POLL_MS = 500

/** One Celery process the launcher started for this run, by its session id. */
export interface ManagedProcess {
  name: string
  sessionId: number
}

/**
 * The run's own Celery worker and beat, as `run_e2e.sh` names them, or null
 * when nothing did: a bare Playwright run against a stack someone else
 * started (ADR 0060) owns no worker, and theirs is not this run's to stop.
 */
export function managedCelery(env: NodeJS.ProcessEnv): ManagedProcess[] | null {
  const worker = env.E2E_CELERY_WORKER_PID
  const beat = env.E2E_CELERY_BEAT_PID
  if (!worker && !beat) return null
  if (!worker || !beat) {
    throw new Error('The launcher named one of the Celery worker and beat but not the other.')
  }
  return [
    { name: 'Celery worker', sessionId: Number.parseInt(worker, 10) },
    { name: 'Celery beat', sessionId: Number.parseInt(beat, 10) },
  ]
}

/** The run's Celery would not stop, so the database was left as the tests made it. */
export class CeleryStillRunningError extends Error {}

export interface ProcessControl {
  /** Ask the process to finish what it is doing and exit. */
  terminate: (sessionId: number) => void
  running: (sessionId: number) => boolean
  sleep: (ms: number) => void
}

/** Any process in the session that has not exited; a zombie has. */
function sessionRunning(sessionId: number): boolean {
  const listed = spawnSync('ps', ['-o', 'stat=', '-s', String(sessionId)], { encoding: 'utf8' })
  return listed.stdout.split('\n').some((state) => state.trim() !== '' && !state.startsWith('Z'))
}

const realProcessControl: ProcessControl = {
  // SIGTERM to the main process is Celery's warm shutdown: the task in hand
  // finishes and no new one starts. To the main process alone (the session's
  // leader), not the group: signalled directly, a pool child dies mid-task.
  terminate: (sessionId) => process.kill(sessionId, 'SIGTERM'),
  running: sessionRunning,
  sleep: sleepSync,
}

/**
 * Run the steps that rewrite the database only once this run's Celery has
 * stopped. A worker mid-task while the dump is replayed deadlocked the
 * restore: the summary-PDF refresh re-queues itself until its backlog is
 * clear, which on a restored database outlasts any fixed wait. If the worker
 * will not stop, nothing is rewritten: restoring under a live writer is the
 * defect, so the run fails with the database as the tests left it.
 */
export function afterCeleryStops(
  managed: ManagedProcess[] | null,
  rewrite: () => void,
  control: ProcessControl = realProcessControl,
  waitMs: number = CELERY_EXIT_WAIT_MS,
): void {
  if (managed === null) {
    console.log('[db] This run did not start Celery, so its worker is left running.')
    rewrite()
    return
  }
  for (const each of managed) {
    if (control.running(each.sessionId)) control.terminate(each.sessionId)
  }
  let waited = 0
  let stillRunning = managed.filter((each) => control.running(each.sessionId))
  while (stillRunning.length > 0 && waited < waitMs) {
    control.sleep(CELERY_EXIT_POLL_MS)
    waited += CELERY_EXIT_POLL_MS
    stillRunning = managed.filter((each) => control.running(each.sessionId))
  }
  if (stillRunning.length > 0) {
    throw new CeleryStillRunningError(
      `${stillRunning.map((each) => each.name).join(' and ')} still running ${waitMs / 1000}s ` +
        'after being asked to stop; the database was not restored under it.',
    )
  }
  console.log("[db] This run's Celery worker and beat have stopped.")
  rewrite()
}

function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)
}

function sqlString(value: string): string {
  return `'${value.replace(/'/g, "''")}'`
}

function sqlNullableString(value: string | null): string {
  if (value === null) {
    return 'NULL'
  }
  return sqlString(value)
}

interface SavedXeroToken {
  id: string
  token_type: string
  access_token: string
  refresh_token: string
  expires_at: string
  scope: string | null
}

/**
 * Save the active XeroApp's token material before the restore wipes it.
 *
 * Xero rotates refresh tokens, so the row in the pre-test backup is already
 * dead if any test (or the ping preflight) triggered a refresh — only the
 * CURRENT row keeps the connection alive across the restore.
 *
 * Raises rather than returning null on failure. It used to swallow everything
 * and return null, which skipped re-injection entirely and left the database
 * holding the backup's consumed token: a dead Xero connection, announced by a
 * console warning nobody reads, and repaired only by driving OAuth by hand.
 * Losing the restore is recoverable from the dump; losing the token is not.
 */
export function saveActiveXeroToken(dbConfig: DbConfig, tokenFile: string): string {
  console.log('[db] Saving current active Xero app token...')
  const row = runPsql(
    dbConfig,
    `SELECT row_to_json(t)
     FROM (
       SELECT id, token_type, access_token, refresh_token, expires_at, scope
       FROM workflow_xeroapp
       WHERE is_active = true
         AND access_token IS NOT NULL
         AND refresh_token IS NOT NULL
       LIMIT 1
     ) t`,
  )
  if (!row) {
    throw new Error(
      'No active Xero app with token material to preserve across the restore. ' +
        'The restore would leave this database without a Xero connection.',
    )
  }
  // Opus: Parsed before the restore, not after: a token that cannot be parsed cannot
  // be re-injected, and finding that out afterwards is finding it out too late.
  parseSavedXeroToken(row)
  fs.writeFileSync(tokenFile, row, { encoding: 'utf8', mode: 0o600 })
  return row
}

function requireString(row: Record<string, unknown>, field: string): string {
  const value = row[field]
  if (typeof value !== 'string') {
    throw new Error(`Saved Xero token is missing '${field}'`)
  }
  return value
}

export function parseSavedXeroToken(raw: string): SavedXeroToken {
  const parsed: unknown = JSON.parse(raw)
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error('Saved Xero token is not an object')
  }
  const row: Record<string, unknown> = { ...parsed }
  const scope = row.scope
  if (scope !== null && scope !== undefined && typeof scope !== 'string') {
    throw new Error("Saved Xero token 'scope' must be a string or null")
  }
  return {
    id: requireString(row, 'id'),
    token_type: requireString(row, 'token_type'),
    access_token: requireString(row, 'access_token'),
    refresh_token: requireString(row, 'refresh_token'),
    expires_at: requireString(row, 'expires_at'),
    scope: scope ?? null,
  }
}

/**
 * Put the live token back onto the row the restore has just overwritten.
 *
 * Opus: Failures propagate, and the caller keeps the side-file: this is the only
 * copy of a credential Xero will not issue again without a human completing
 * consent, so a swallowed failure here trades a loud stop for a silently dead
 * connection.
 */
export function reinjectXeroToken(dbConfig: DbConfig, xeroAppTokenRow: string): void {
  const token = parseSavedXeroToken(xeroAppTokenRow)
  const updated = runPsql(
    dbConfig,
    `UPDATE workflow_xeroapp
     SET token_type = ${sqlString(token.token_type)},
         access_token = ${sqlString(token.access_token)},
         refresh_token = ${sqlString(token.refresh_token)},
         expires_at = ${sqlString(token.expires_at)},
         scope = ${sqlNullableString(token.scope)}
     WHERE id = ${sqlString(token.id)}
     RETURNING id`,
  )
  if (!updated) {
    throw new Error(
      `Re-injecting the Xero token matched no row with id ${token.id}. The restored ` +
        "database is left with the backup's consumed token.",
    )
  }
  console.log('[db] Active Xero app token restored.')
}

/** Preserve before any fake refresh; managed runs keep custody until their writers stop. */
export function beginFakeTokenSnapshot(): string | null {
  if (selectedXeroMode() !== 'fake') return null
  const managed = process.env.E2E_XERO_TOKEN_SNAPSHOT
  if (managed) {
    parseSavedXeroToken(fs.readFileSync(managed, 'utf8'))
    return managed
  }
  fs.mkdirSync(getBackupsDir(), { recursive: true })
  const dir = fs.mkdtempSync(path.join(getBackupsDir(), 'fake-xero-'))
  fs.chmodSync(dir, 0o700)
  const file = path.join(dir, 'token.json')
  saveActiveXeroToken(getDbConfig(), file)
  return file
}

export function finishFakeTokenSnapshot(file: string | null): void {
  if (file === null || file === process.env.E2E_XERO_TOKEN_SNAPSHOT) return
  try {
    reinjectXeroToken(getDbConfig(), fs.readFileSync(file, 'utf8'))
  } catch (error) {
    console.error(`[xero] Credential restore failed; recovery file retained: ${file}`)
    throw error
  }
  fs.unlinkSync(file)
  fs.rmdirSync(path.dirname(file))
}

function printXeroCleanupFailureBanner(reason: string): void {
  console.error('')
  console.error('================================================================')
  console.error("E2E TEARDOWN COULD NOT REMOVE THIS RUN'S XERO OBJECTS")
  console.error('================================================================')
  console.error(reason)
  console.error('')
  console.error('The restore below still runs, and it erases the local rows that')
  console.error("name those objects — so this run's invoices, quotes, purchase")
  console.error('orders and contacts are now findable only in the organisation.')
  console.error('')
  console.error('Clear them with (dry run first):')
  console.error('  uv run python manage.py e2e_xero_sweep')
  console.error('  uv run python manage.py e2e_xero_sweep --confirm')
  console.error('================================================================')
}

function printRestoreFailureBanner(backupFile: string, dbConfig: DbConfig, reason: string): void {
  const singleTx = '--single-transaction'
  const onErrorStop = '-v ON_ERROR_STOP=1'
  console.error('')
  console.error('================================================================')
  console.error('E2E TEARDOWN FAILED TO RESTORE DATABASE')
  console.error('================================================================')
  console.error(reason)
  console.error('')
  console.error('Your dev DB currently reflects whatever the tests mutated, NOT')
  console.error('the pre-test state. The backup has been preserved.')
  console.error('')
  console.error('Backup preserved at:')
  console.error(`  ${backupFile}`)
  console.error('')
  console.error('Recover manually with:')
  console.error(`  PGPASSWORD=$DB_PASSWORD psql ${onErrorStop} ${singleTx} \\`)
  const portArg = dbConfig.port ? `-p ${dbConfig.port} ` : ''
  console.error(
    `    -h ${dbConfig.host} ${portArg}-U ${dbConfig.user} -d ${dbConfig.database} -f ${backupFile}`,
  )
  console.error('')
  console.error('Do NOT run E2E again until the DB is restored.')
  console.error('================================================================')
}

function printMissingBackupBanner(backupFile: string | undefined, reason: string): void {
  console.error('')
  console.error('================================================================')
  console.error('E2E TEARDOWN CANNOT RESTORE DATABASE')
  console.error('================================================================')
  console.error(reason)
  console.error('The E2E lock has been preserved. The pre-test backup is unavailable,')
  console.error('so inspect the database before removing the lock or running E2E again.')
  if (backupFile) console.error(`Expected backup path: ${backupFile}`)
  console.error('================================================================')
}

/** Resolve a completed setup's backup without allowing a missing file to look recoverable. */
export function requireBackupFile(
  lockContents: string,
  fileExists: (file: string) => boolean = fs.existsSync,
): string {
  const backupFile = lockContents.split('\n')[1]?.trim()
  if (!backupFile) throw new Error('Setup did not record a backup path in the E2E lock.')
  if (!fileExists(backupFile)) throw new Error(`Backup file not found: ${backupFile}`)
  return backupFile
}

export function restoreDatabase(lockContents: string): void {
  console.log('\n[db] Restoring database after tests...')
  const dbConfig = getDbConfig()
  const xeroMode = recordedXeroMode(lockContents)
  const fakeSnapshot = xeroMode === 'fake' ? lockContents.split('\n')[4]?.trim() : null
  if (xeroMode === 'fake' && !fakeSnapshot)
    throw new Error('Fake run has no original-token snapshot.')
  if (fakeSnapshot) parseSavedXeroToken(fs.readFileSync(fakeSnapshot, 'utf8'))

  let backupFile: string
  try {
    backupFile = requireBackupFile(lockContents)
  } catch (error) {
    const expectedPath = lockContents.split('\n')[1]?.trim() || undefined
    const reason = error instanceof Error ? error.message : String(error)
    printMissingBackupBanner(expectedPath, reason)
    throw error
  }

  // Capture migration count BEFORE restore so the integrity check can confirm
  // the backup's migration state matches what we expect.
  let expectedMigrationCount: number | null = null
  try {
    expectedMigrationCount = parseInt(
      runPsql(dbConfig, `SELECT COUNT(*) FROM django_migrations`),
      10,
    )
  } catch (e) {
    console.warn(
      `[db] Could not read django_migrations count (${e instanceof Error ? e.message : String(e)}); ` +
        'integrity check will skip the migration comparison.',
    )
  }

  console.log(
    `[db] Waiting ${PRE_RESTORE_XERO_SETTLE_MS / 1000}s for in-flight Xero/Celery work before restore...`,
  )
  sleepSync(PRE_RESTORE_XERO_SETTLE_MS)

  // Before the Xero cleanup, not just before the restore: the cleanup deletes
  // the run's [TEST] jobs, and a job change queues the summary-PDF refresh, so
  // a worker still up would start writing again right ahead of the restore.
  try {
    afterCeleryStops(managedCelery(process.env), () =>
      rewriteDatabase({ dbConfig, xeroMode, backupFile, expectedMigrationCount, fakeSnapshot }),
    )
  } catch (error) {
    // Everything past the stop prints its own banner; this one had no chance to.
    if (error instanceof CeleryStillRunningError) {
      printRestoreFailureBanner(backupFile, dbConfig, error.message)
    }
    throw error
  }
}

interface RewriteInputs {
  dbConfig: DbConfig
  xeroMode: ReturnType<typeof recordedXeroMode>
  backupFile: string
  expectedMigrationCount: number | null
  fakeSnapshot: string | null | undefined
}

/** Clean this run out of Xero, then replace the database with the pre-run dump. */
function rewriteDatabase({
  dbConfig,
  xeroMode,
  backupFile,
  expectedMigrationCount,
  fakeSnapshot,
}: RewriteInputs): void {
  // Remove this run's writes from the Xero organisation. After the settle so
  // in-flight Celery work has finished creating them, and before the restore
  // because the restore erases the local rows that carry their Xero ids —
  // this is the last moment anything knows what the run made.
  //
  // Reported rather than raised: the restore is the one step whose failure
  // costs hours, so a Xero refusal must not take it down with it. The banner
  // names the sweep, which finds the same objects by reading the organisation.
  removeThisRunsXeroObjects()

  // The run's vendor calls, before the restore erases them: which routes the
  // suite reached and what the vendor answered. A real run is the one time
  // that inventory is in hand (ADR 0050), and it is what a route missing from
  // the fake Xero is found by (ADR 0060).
  exportVendorCalls(dbConfig, backupFile)

  // Save AFTER the settle and after the Xero cleanup (v1 saved before the
  // settle): both can trigger a refresh, and Xero's refresh token is
  // single-use, so reinjecting a copy taken earlier would strand the next run
  // on a consumed token. The cleanup is the likelier of the two — it makes a
  // real Xero call per document.
  //
  // Fake refreshes can overwrite access tokens before the database backup exists.
  // The original snapshot belongs to setup, or to the launcher until its writers stop.
  const xeroTokenFile = `${backupFile}.xero-app-token.json`
  const xeroAppTokenRow = xeroMode === 'fake' ? null : saveActiveXeroToken(dbConfig, xeroTokenFile)

  // Atomic restore: -v ON_ERROR_STOP=1 bails psql at the first SQL error
  // and --single-transaction wraps the whole dump replay in one BEGIN/COMMIT.
  // Any failure rolls back to the pre-teardown state — never a partial
  // restore.
  console.log('[db] Restoring from backup (atomic: --single-transaction + ON_ERROR_STOP)...')
  const restoreArgs = ['-v', 'ON_ERROR_STOP=1', '--single-transaction', '-h', dbConfig.host]
  if (dbConfig.port) {
    restoreArgs.push('-p', dbConfig.port)
  }
  restoreArgs.push('-U', dbConfig.user, '-d', dbConfig.database, '-f', backupFile)
  const result = spawnSync('psql', restoreArgs, {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PGPASSWORD: dbConfig.password },
  })

  const stderr = result.stderr?.toString() || ''
  if (stderr.trim()) {
    console.log('[db] psql restore output:', stderr)
  }
  try {
    assertSpawnSucceeded('Database restore', result)
  } catch (error) {
    printRestoreFailureBanner(
      backupFile,
      dbConfig,
      `${error instanceof Error ? error.message : String(error)}. The transaction rolled back; the DB was ` +
        `NOT mutated by the restore itself, but still reflects test mutations.`,
    )
    throw error
  }

  // Verify structural sanity before we trust the restore and delete the
  // backup. Catches the class of silent damage partial psql restores
  // produce (duplicated singletons, missing PKs).
  console.log('[db] Running post-restore integrity check...')
  const integrity = runIntegrityCheck(dbConfig, expectedMigrationCount)
  if (!integrity.ok) {
    printRestoreFailureBanner(
      backupFile,
      dbConfig,
      `Integrity check failed:\n  - ${integrity.issues.join('\n  - ')}`,
    )
    throw new Error(`Post-restore integrity check failed: ${integrity.issues.join('; ')}`)
  }

  // Re-inject the saved active Xero app token so the connection stays live.
  // Throws on failure, which leaves the side-file below undeleted — the token
  // stays recoverable by hand instead of being lost with the process.
  if (xeroAppTokenRow !== null) {
    reinjectXeroToken(dbConfig, xeroAppTokenRow)
  }

  // Sync sequences after restore
  console.log('[db] Syncing sequences...')
  try {
    syncSequences()
  } catch (error) {
    printRestoreFailureBanner(
      backupFile,
      dbConfig,
      `Sequence sync failed after restore: ${error instanceof Error ? error.message : String(error)}`,
    )
    throw error
  }

  // Prove the restored DB is E2E-clean before deleting the backup.
  console.log('[db] Running post-restore E2E safety check...')
  const safety = checkSafeToTest(dbConfig)
  if (!safety.clean) {
    printRestoreFailureBanner(
      backupFile,
      dbConfig,
      `E2E safety check failed after restore:\n  - ${safety.issues.join('\n  - ')}`,
    )
    throw new Error(`Post-restore E2E safety check failed: ${safety.issues.join('; ')}`)
  }

  // Backup + token side-file have served their purpose. Delete only after
  // the full pipeline succeeded — restore + integrity check + token
  // reinjection + sequences + E2E safety check.
  finishFakeTokenSnapshot(fakeSnapshot ?? null)
  fs.unlinkSync(backupFile)
  fs.rmSync(xeroTokenFile, { force: true })

  console.log('[db] Database restored successfully.')
}

/**
 * Write this run's vendor calls, grouped by route and status, beside the
 * test results. "This run" is everything since the pre-run dump was taken;
 * the dump file's own timestamp is that moment, and the restore that follows
 * this export erases the rows.
 */
function exportVendorCalls(dbConfig: DbConfig, backupFile: string): void {
  const since = fs.statSync(backupFile).mtime.toISOString()
  const outFile = path.join(runStateDir(), 'test-results', 'vendor-calls.csv')
  const rows = runPsql(
    dbConfig,
    `SELECT vendor, method, endpoint, status_code, COUNT(*)
       FROM observability_vendorcall
      WHERE occurred_at >= '${since}'
      GROUP BY vendor, method, endpoint, status_code
      ORDER BY vendor, endpoint, method, status_code`,
  )
  fs.mkdirSync(path.dirname(outFile), { recursive: true })
  fs.writeFileSync(
    outFile,
    `vendor,method,endpoint,status_code,calls\n${rows.replaceAll('|', ',')}\n`,
  )
  console.log(`[vendor] ${rows ? rows.split('\n').length : 0} route(s) this run -> ${outFile}`)
}

function removeThisRunsXeroObjects(): void {
  console.log("\n[xero] Removing this run's Xero objects...")
  try {
    runE2ECleanup(true)
  } catch (error) {
    printXeroCleanupFailureBanner(error instanceof Error ? error.message : String(error))
  }
}

export default function globalTeardown(): void {
  if (!fs.existsSync(LOCK_FILE)) {
    console.warn('[db] No lock file found. Skipping restore.')
    return
  }

  const lockContents = fs.readFileSync(LOCK_FILE, 'utf8')
  const lockedPid = lockContents.split('\n')[0]?.trim()
  if (lockedPid !== process.pid.toString()) {
    // Lock predates this process — a previous run was killed before its
    // own teardown ran. Its backup path on line 2 is NOT ours to act on;
    // restoring from it would wipe whatever the user has done since the
    // killed run. Leave both files in place so the user can decide.
    console.warn(
      `[db] Lock owned by PID ${lockedPid} (this process is ${process.pid}). ` +
        `Stale lock from a prior run — not restoring, not deleting. ` +
        `Inspect ${LOCK_FILE} and the backup it points to manually.`,
    )
    return
  }

  recordedXeroMode(lockContents)
  try {
    restoreDatabase(lockContents)
  } finally {
    // Close this run's Xero sync window even when the restore fails: the
    // tests are over either way, and an open window would let the hourly
    // poll replay this run's Xero artifacts while the operator recovers.
    // Until now it was open, so nothing the run created in Xero was
    // suppressed on the way back in — that round trip is what the run
    // exercises.
    const runId = lockContents.split('\n')[2]?.trim()
    if (!runId) {
      console.warn('[e2e] No run id in lock file; sync window left open.')
    } else {
      closeSyncWindow(runId)
      console.log(`[e2e] Run ${runId}: Xero sync window closed.`)
    }
  }

  fs.unlinkSync(LOCK_FILE)
}
