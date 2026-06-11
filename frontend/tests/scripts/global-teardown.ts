import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'
import * as fs from 'fs'
import os from 'os'
import {
  checkSafeToTest,
  DbConfig,
  getDbConfig,
  runIntegrityCheck,
  runPsql,
  syncSequences,
} from './db-backup-utils'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')
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

function restoreDatabase(lockContents: string) {
  console.log('\n[db] Restoring database after tests...')
  const dbConfig = getDbConfig()

  const backupFile = lockContents.split('\n')[1]?.trim()
  if (!backupFile) {
    console.warn(
      '[db] Setup did not complete a backup (no backup path in lock file). Skipping restore.',
    )
    return
  }
  if (!fs.existsSync(backupFile)) {
    console.warn(`[db] Backup file not found: ${backupFile}. Skipping restore.`)
    return
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
      `[db] Could not read django_migrations count (${(e as Error).message}); ` +
        'integrity check will skip the migration comparison.',
    )
  }

  // Save the current active Xero app token before restore — the backup
  // contains stale tokens from when the backup was taken, which will likely
  // have expired. Persist to disk alongside the backup so a mid-teardown
  // crash doesn't lose it.
  console.log('[db] Saving current active Xero app token...')
  let xeroAppTokenRow: string | null = null
  const xeroTokenFile = `${backupFile}.xero-app-token.json`
  try {
    xeroAppTokenRow = runPsql(
      dbConfig,
      `SELECT row_to_json(t)
       FROM (
         SELECT id, tenant_id, token_type, access_token, refresh_token, expires_at, scope
         FROM workflow_xeroapp
         WHERE is_active = true
           AND access_token IS NOT NULL
           AND refresh_token IS NOT NULL
         LIMIT 1
       ) t`,
    )
    if (xeroAppTokenRow) {
      fs.writeFileSync(xeroTokenFile, xeroAppTokenRow, 'utf8')
    }
  } catch {
    console.warn('[db] Could not read active Xero app token (table may not exist yet). Skipping.')
  }

  // Let in-flight Celery/Xero work finish against the dirty test DB before
  // restoring the backup. If we restore immediately, a webhook/full-sync task
  // that was already queued can recreate [TEST] clients in the clean DB a few
  // seconds later. Waiting here makes those writes part of the state we wipe.
  console.log(
    `[db] Waiting ${PRE_RESTORE_XERO_SETTLE_MS / 1000}s for in-flight Xero/Celery work before restore...`,
  )
  sleepSync(PRE_RESTORE_XERO_SETTLE_MS)

  // Atomic restore: -v ON_ERROR_STOP=1 bails psql at the first SQL error
  // and --single-transaction wraps the whole dump replay in one BEGIN/COMMIT.
  // Any failure rolls back to the pre-teardown state — never a partial
  // restore.
  console.log('[db] Restoring from backup (atomic: --single-transaction + ON_ERROR_STOP)...')
  const result = spawnSync(
    'psql',
    [
      '-v',
      'ON_ERROR_STOP=1',
      '--single-transaction',
      '-h',
      dbConfig.host,
      '-p',
      dbConfig.port,
      '-U',
      dbConfig.user,
      '-d',
      dbConfig.database,
      '-f',
      backupFile,
    ],
    {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PGPASSWORD: dbConfig.password },
    },
  )

  const stderr = result.stderr?.toString() || ''
  if (stderr.trim()) {
    console.log('[db] psql restore output:', stderr)
  }
  if (result.status !== 0) {
    printRestoreFailureBanner(
      backupFile,
      dbConfig,
      `psql exited ${result.status}. The transaction rolled back; the DB was ` +
        `NOT mutated by the restore itself, but still reflects test mutations.`,
    )
    throw new Error(`Database restore failed (exit code ${result.status})`)
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
    try {
      const token = JSON.parse(xeroAppTokenRow)
      runPsql(
        dbConfig,
        `UPDATE workflow_xeroapp
         SET tenant_id = ${sqlNullableString(token.tenant_id)},
             token_type = ${sqlString(token.token_type)},
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

  // Sync sequences after restore
  console.log('[db] Syncing sequences...')
  syncSequences(dbConfig)

  // Prove the restored DB is E2E-clean before deleting the backup. This also
  // catches any Xero/Celery work that still managed to land after the restore.
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
  if (fs.existsSync(xeroTokenFile)) {
    fs.unlinkSync(xeroTokenFile)
  }

  console.log('[db] Database restored successfully.')
}

export default async function globalTeardown() {
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

// Auto-run when executed directly (not imported as module)
const isDirectRun = process.argv[1]?.includes('global-teardown')
if (isDirectRun) {
  globalTeardown()
}
