import fs from 'fs'
import os from 'os'
import path from 'path'
import {
  checkSafeToTest,
  formatTimestamp,
  getBackupsDir,
  getDbConfig,
  runPgDump,
  syncSequences,
} from './db-backup-utils'
import { openSyncWindow } from './e2e-sync-windows'

const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

/**
 * Identifier for this run: labels the lock file (line 3, where teardown reads
 * it) and this run's Xero sync window.
 */
function mintRunId(): string {
  return Math.random().toString(36).substring(2, 10)
}

/**
 * The backend's own address, not the vite preview: Playwright runs
 * globalSetup BEFORE it launches the webServer, so localhost:4173 is not up
 * yet in a bare `npm run test:e2e`. run_e2e.sh health-checks this same URL
 * before handing over.
 */
const BACKEND_URL = 'http://127.0.0.1:8000'

async function getAuthCookie(): Promise<string> {
  const username = process.env.E2E_TEST_USERNAME
  const password = process.env.E2E_TEST_PASSWORD
  if (!username || !password) {
    throw new Error('E2E_TEST_USERNAME and E2E_TEST_PASSWORD must be set in .env.test')
  }

  const loginResponse = await fetch(`${BACKEND_URL}/api/accounts/token/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    signal: AbortSignal.timeout(15_000),
  })
  if (!loginResponse.ok) {
    throw new Error(`E2E preflight login failed with status ${loginResponse.status}`)
  }
  const setCookies = loginResponse.headers.getSetCookie()
  const accessCookie = setCookies.find((c) => c.startsWith('access_token='))
  const cookiePair = accessCookie?.split(';')[0]
  if (!cookiePair) {
    throw new Error('No access_token cookie in login response')
  }
  return cookiePair // "access_token=<jwt>"
}

/**
 * Safety check: verify Xero is connected and whether the backend is pointing
 * at the production Xero app. Production Xero writes require XERO_READONLY.
 * Does NOT attempt to connect or refresh tokens.
 */
async function checkXeroStatus(): Promise<{
  connected: boolean
  xeroReadonly: boolean
  productionClient: boolean | null
}> {
  const cookieValue = await getAuthCookie()

  // Generous: ping may perform a real token refresh against Xero.
  const response = await fetch(`${BACKEND_URL}/api/xero/ping/`, {
    headers: { Cookie: cookieValue },
    signal: AbortSignal.timeout(60_000),
  })
  if (!response.ok) {
    // A 500 here is an operational failure (e.g. token refresh failed with
    // an error_id) — reporting it as "not connected" would send the operator
    // to redo OAuth instead of reading the error. Fail with the real body.
    throw new Error(`Xero ping failed with HTTP ${response.status}: ${await response.text()}`)
  }
  const data: unknown = await response.json()
  if (typeof data !== 'object' || data === null) {
    return { connected: false, xeroReadonly: false, productionClient: null }
  }
  const payload: Record<string, unknown> = { ...data }
  return {
    connected: payload.connected === true,
    // Missing xero_readonly (wrong backend build) must fail, not pass silently.
    xeroReadonly: payload.xero_readonly === true,
    // Missing production-client classification must fail closed when connected.
    productionClient:
      typeof payload.xero_production_client === 'boolean' ? payload.xero_production_client : null,
  }
}

/** Turn a ping result into blocking issues; exported so the guard itself is testable. */
export function xeroPreflightIssues(xeroStatus: {
  connected: boolean
  xeroReadonly: boolean
  productionClient: boolean | null
}): string[] {
  const issues: string[] = []
  if (!xeroStatus.connected) {
    issues.push('Xero is not connected. Complete the OAuth flow (/api/xero/authenticate/) first.')
    return issues
  }
  console.log('[xero] Xero is connected.')
  if (xeroStatus.productionClient === null) {
    issues.push(
      'Backend did not report whether the active Xero app is production. ' +
        'Deploy the backend ping update before running E2E.',
    )
  } else if (xeroStatus.productionClient && !xeroStatus.xeroReadonly) {
    issues.push(
      'Backend is using the production Xero app with writes enabled. ' +
        'Restart the backend and any celery worker with XERO_READONLY=true, ' +
        'or switch the active Xero app to a non-production client.',
    )
  } else if (xeroStatus.productionClient) {
    console.log('[xero] Backend is using the production Xero app in XERO_READONLY mode.')
  } else {
    console.log('[xero] Backend is using a non-production Xero app.')
  }
  return issues
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

export default async function globalSetup(): Promise<void> {
  acquireE2ELock(LOCK_FILE, process.pid)

  // Playwright skips globalTeardown when globalSetup throws, so any failure
  // past this point must clean up the lock (and any partial dump) here —
  // otherwise the next run refuses to start for a dead PID.
  let backupFile: string | null = null
  try {
    // All checks are read-only — they abort if something is wrong, never fix it.
    console.log('[xero] Checking Xero connection...')
    const xeroIssues = xeroPreflightIssues(await checkXeroStatus())
    if (xeroIssues.length > 0) {
      const issueList = xeroIssues.map((i) => `  - ${i}`).join('\n')
      throw new Error(`E2E Xero pre-flight checks failed:\n${issueList}`)
    }

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

    // Open this run's Xero sync window BEFORE any test can write to Xero.
    // Left open for the whole run (open windows suppress nothing); teardown
    // closes it, making the run's Xero artifacts inert to the hourly sync.
    openSyncWindow(runId)
    console.log(`[e2e] Run ${runId}: Xero sync window opened.`)

    // Take backup
    console.log('[db] Backing up database before tests...')
    const backupDir = getBackupsDir()
    fs.mkdirSync(backupDir, { recursive: true })

    backupFile = path.join(backupDir, `backup_${formatTimestamp(new Date())}.sql`)
    runPgDump(dbConfig, backupFile)

    // Record backup path in the lock file (line 2) so teardown knows a backup
    // was taken in this run and where to find it, then the run id (line 3).
    // Order matters: teardown reads the backup path positionally.
    fs.appendFileSync(LOCK_FILE, `\n${backupFile}\n${runId}`, 'utf8')

    console.log(`[db] Backup complete: ${backupFile}`)
  } catch (error) {
    fs.rmSync(LOCK_FILE, { force: true })
    if (backupFile) {
      // runPgDump removes its own partial dumps; this covers failures after
      // the dump completed but before the lock recorded it — teardown would
      // never find such a backup, so keeping it only accumulates orphans.
      fs.rmSync(backupFile, { force: true })
    }
    throw error
  }
}
