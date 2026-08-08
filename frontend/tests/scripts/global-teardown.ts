// The sync-window close is NOT ported — see the seam comment in
// global-setup.ts. Token save/reinject and the settle wait are live below.
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import os from 'os'
import path from 'path'
import {
  checkSafeToTest,
  getDbConfig,
  runIntegrityCheck,
  runPsql,
  syncSequences,
  type DbConfig,
} from './db-backup-utils'
import { assertSpawnSucceeded } from './process-result'

const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

// Let in-flight Celery/Xero work finish against the dirty test DB before the
// restore replaces it — a queued webhook/full-sync task can otherwise recreate
// [TEST] rows in the clean DB seconds after restore. Ported at v1's value even
// though slice 1 has no async Xero work yet; slice 2's sync engine relies on it.
const PRE_RESTORE_XERO_SETTLE_MS = 90_000

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
 * Xero rotates refresh tokens, so the row in the pre-test backup is already
 * dead if any test (or the ping preflight) triggered a refresh — only the
 * CURRENT row keeps the connection alive across the restore.
 */
function saveActiveXeroToken(dbConfig: DbConfig, tokenFile: string): string | null {
  console.log('[db] Saving current active Xero app token...')
  try {
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
    if (row) {
      fs.writeFileSync(tokenFile, row, 'utf8')
      return row
    }
  } catch (e) {
    console.warn('[db] Could not read active Xero app token:', e instanceof Error ? e.message : e)
  }
  return null
}

function requireString(row: Record<string, unknown>, field: string): string {
  const value = row[field]
  if (typeof value !== 'string') {
    throw new Error(`Saved Xero token is missing '${field}'`)
  }
  return value
}

function parseSavedXeroToken(raw: string): SavedXeroToken {
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

function reinjectXeroToken(dbConfig: DbConfig, xeroAppTokenRow: string): void {
  try {
    const token = parseSavedXeroToken(xeroAppTokenRow)
    runPsql(
      dbConfig,
      `UPDATE workflow_xeroapp
       SET token_type = ${sqlString(token.token_type)},
           access_token = ${sqlString(token.access_token)},
           refresh_token = ${sqlString(token.refresh_token)},
           expires_at = ${sqlString(token.expires_at)},
           scope = ${sqlNullableString(token.scope)}
       WHERE id = ${sqlString(token.id)}`,
    )
    console.log('[db] Active Xero app token restored.')
  } catch (e) {
    console.warn('[db] Failed to restore active Xero app token:', e)
  }
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

function restoreDatabase(lockContents: string): void {
  console.log('\n[db] Restoring database after tests...')
  const dbConfig = getDbConfig()

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

  // Save AFTER the settle (v1 saved before it): a refresh completing during
  // the wait rotates the refresh token, and reinjecting the pre-settle copy
  // would strand the next run on a consumed token.
  const xeroTokenFile = `${backupFile}.xero-app-token.json`
  const xeroAppTokenRow = saveActiveXeroToken(dbConfig, xeroTokenFile)

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
  if (xeroAppTokenRow) {
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
  fs.unlinkSync(backupFile)
  fs.rmSync(xeroTokenFile, { force: true })

  console.log('[db] Database restored successfully.')
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

  restoreDatabase(lockContents)

  fs.unlinkSync(LOCK_FILE)
}
