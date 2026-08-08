// Xero token save/reinject, the pre-restore Celery/Xero settle wait and the
// sync-window close are NOT ported — see the seam comment in global-setup.ts.
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

const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

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

function restoreDatabase(lockContents: string): void {
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
      `[db] Could not read django_migrations count (${e instanceof Error ? e.message : String(e)}); ` +
        'integrity check will skip the migration comparison.',
    )
  }

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

  // Sync sequences after restore
  console.log('[db] Syncing sequences...')
  syncSequences()

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

  // The backup has served its purpose. Delete only after the full pipeline
  // succeeded — restore + integrity check + sequences + E2E safety check.
  fs.unlinkSync(backupFile)

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
