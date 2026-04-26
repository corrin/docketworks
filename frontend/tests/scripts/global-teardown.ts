import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'
import * as fs from 'fs'
import os from 'os'
import {
  DbConfig,
  getBackendEnv,
  getDbConfig,
  runIntegrityCheck,
  runPsql,
  syncSequences,
} from './db-backup-utils'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
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

function restoreDatabase() {
  console.log('\n[db] Restoring database after tests...')
  const dbConfig = getDbConfig()

  if (!fs.existsSync(LOCK_FILE)) {
    console.warn('[db] No lock file found. Skipping restore.')
    return
  }

  const lockContents = fs.readFileSync(LOCK_FILE, 'utf8')
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

  // Save the current Xero token before restore — the backup contains a stale
  // token from when the backup was taken, which will likely have expired.
  // Persist to disk alongside the backup so a mid-teardown crash doesn't
  // lose it.
  console.log('[db] Saving current Xero token...')
  let xeroTokenRow: string | null = null
  const xeroTokenFile = `${backupFile}.xero-token.json`
  try {
    xeroTokenRow = runPsql(dbConfig, `SELECT row_to_json(t) FROM workflow_xerotoken t LIMIT 1`)
    if (xeroTokenRow) {
      fs.writeFileSync(xeroTokenFile, xeroTokenRow, 'utf8')
    }
  } catch {
    console.warn('[db] Could not read Xero token (table may not exist yet). Skipping.')
  }

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

  // Re-inject the saved Xero token so the connection stays live.
  if (xeroTokenRow) {
    try {
      const token = JSON.parse(xeroTokenRow)
      runPsql(
        dbConfig,
        `DELETE FROM workflow_xerotoken;
         INSERT INTO workflow_xerotoken (id, tenant_id, token_type, access_token, refresh_token, expires_at, scope)
         VALUES (
           ${token.id},
           '${token.tenant_id}',
           '${token.token_type}',
           '${token.access_token}',
           '${token.refresh_token}',
           '${token.expires_at}',
           '${token.scope}'
         )`,
      )
      console.log('[db] Xero token restored.')
    } catch (e) {
      console.warn('[db] Failed to restore Xero token:', e)
    }
  }

  // Sync sequences after restore
  console.log('[db] Syncing sequences...')
  syncSequences(dbConfig)

  // Backup + token side-file have served their purpose. Delete only after
  // the full pipeline succeeded — restore + integrity check + token
  // reinjection + sequences.
  fs.unlinkSync(backupFile)
  if (fs.existsSync(xeroTokenFile)) {
    fs.unlinkSync(xeroTokenFile)
  }

  console.log('[db] Database restored successfully.')
}

async function enableServerCache(): Promise<void> {
  const appDomain = getBackendEnv().APP_DOMAIN
  if (!appDomain) {
    throw new Error('APP_DOMAIN must be set in backend .env')
  }
  const frontendUrl = `https://${appDomain}`

  const username = process.env.E2E_TEST_USERNAME
  const password = process.env.E2E_TEST_PASSWORD
  if (!username || !password) {
    throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env')
  }

  const loginResponse = await fetch(`${frontendUrl}/api/accounts/token/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!loginResponse.ok) {
    throw new Error(`Login failed with status ${loginResponse.status}`)
  }
  const setCookies = loginResponse.headers.getSetCookie()
  const accessCookie = setCookies.find((c) => c.startsWith('access_token='))
  if (!accessCookie) {
    throw new Error('No access_token cookie in login response')
  }
  const cookieValue = accessCookie.split(';')[0]

  const response = await fetch(`${frontendUrl}/api/enable_cache/`, {
    method: 'POST',
    headers: { Cookie: cookieValue },
  })
  if (!response.ok) {
    throw new Error(`enable_cache failed with status ${response.status}`)
  }
  console.log('[cache] Server cache re-enabled.')
}

export default async function globalTeardown() {
  try {
    await enableServerCache()
  } catch (e) {
    // Don't let a failed re-enable block the rest of teardown — the
    // server-side resume_after timer is the safety net.
    console.error('Failed to re-enable server cache:', e)
  }

  restoreDatabase()

  if (fs.existsSync(LOCK_FILE)) {
    fs.unlinkSync(LOCK_FILE)
  }
}

// Auto-run when executed directly (not imported as module)
const isDirectRun = process.argv[1]?.includes('global-teardown')
if (isDirectRun) {
  globalTeardown()
}
