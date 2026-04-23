import { spawnSync } from 'child_process'
import fs from 'fs'
import os from 'os'
import path from 'path'
import {
  getBackendEnv,
  getBackupsDir,
  getDbConfig,
  checkSafeToTest,
  syncSequences,
} from './db-backup-utils'

const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

function formatTimestamp(date: Date): string {
  const pad = (value: number) => value.toString().padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`
}

function getFrontendUrl(): string {
  const appDomain = getBackendEnv().APP_DOMAIN
  if (!appDomain) {
    throw new Error('APP_DOMAIN must be set in backend .env')
  }
  return `https://${appDomain}`
}

async function getAuthCookie(frontendUrl: string): Promise<string> {
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
  return accessCookie.split(';')[0] // "access_token=<jwt>"
}

/**
 * Read-only check: verify Xero is connected by hitting the ping endpoint.
 * Does NOT attempt to connect or refresh tokens.
 */
async function checkXeroConnected(): Promise<boolean> {
  const frontendUrl = getFrontendUrl()
  const cookieValue = await getAuthCookie(frontendUrl)

  const response = await fetch(`${frontendUrl}/api/xero/ping/`, {
    headers: { Cookie: cookieValue },
  })
  if (!response.ok) return false
  const data = (await response.json()) as { connected: boolean }
  return data.connected === true
}

/**
 * Disable per-worker solo caching for the duration of the E2E run. Auto-
 * resumes after an hour as a safety net in case teardown doesn't run.
 */
async function disableServerCache(): Promise<void> {
  const frontendUrl = getFrontendUrl()
  const cookieValue = await getAuthCookie(frontendUrl)
  const response = await fetch(`${frontendUrl}/api/disable_cache/?resume_after=3600`, {
    method: 'POST',
    headers: { Cookie: cookieValue },
  })
  if (!response.ok) {
    throw new Error(`disable_cache failed with status ${response.status}`)
  }
  const body = (await response.json()) as { disabled_until: string }
  console.log(`[cache] Server cache disabled until ${body.disabled_until}`)
}

export default async function globalSetup() {
  if (fs.existsSync(LOCK_FILE)) {
    const pid = fs.readFileSync(LOCK_FILE, 'utf8').trim()
    throw new Error(`E2E tests already running (PID: ${pid}). Kill it or delete ${LOCK_FILE}`)
  }
  fs.writeFileSync(LOCK_FILE, process.pid.toString())

  // All checks are read-only — they abort if something is wrong, never fix it.
  const issues: string[] = []

  // Check Xero connection
  console.log('[xero] Checking Xero connection...')
  const xeroConnected = await checkXeroConnected()
  if (!xeroConnected) {
    issues.push('Xero is not connected. Navigate to /xero in the app to connect.')
  } else {
    console.log('[xero] Xero is connected.')
  }

  // Check database is clean
  console.log('[db] Checking database is safe for E2E tests...')
  const dbConfig = getDbConfig()
  const dbCheck = checkSafeToTest(dbConfig)
  issues.push(...dbCheck.issues)

  if (issues.length > 0) {
    // Clean up lock file before aborting
    if (fs.existsSync(LOCK_FILE)) fs.unlinkSync(LOCK_FILE)
    const issueList = issues.map((i) => `  - ${i}`).join('\n')
    throw new Error(
      `E2E pre-flight checks failed:\n${issueList}\n\n` +
        `Run 'npm run test:e2e:reset' to clean test data and fix sequences.`,
    )
  }
  console.log('[db] Database is clean.')

  // Sync sequences as a safety net (idempotent, fast)
  console.log('[db] Syncing sequences...')
  syncSequences(dbConfig)
  console.log('[db] Sequences synced.')

  // Take backup
  console.log('[db] Backing up database before tests...')
  const backupDir = getBackupsDir()
  fs.mkdirSync(backupDir, { recursive: true })

  const backupFile = path.join(backupDir, `backup_${formatTimestamp(new Date())}.sql`)
  const outputFd = fs.openSync(backupFile, 'w')

  const result = spawnSync(
    'pg_dump',
    ['--clean', '-h', dbConfig.host, '-p', dbConfig.port, '-U', dbConfig.user, dbConfig.database],
    {
      stdio: ['ignore', outputFd, 'inherit'],
      env: { ...process.env, PGPASSWORD: dbConfig.password },
    },
  )

  fs.closeSync(outputFd)

  if (result.status !== 0) {
    throw new Error(`Database backup failed (exit code ${result.status}).`)
  }

  // Record backup path in the lock file (line 2) so teardown knows a backup
  // was taken in this run and where to find it.
  fs.appendFileSync(LOCK_FILE, `\n${backupFile}`, 'utf8')

  console.log(`[db] Backup complete: ${backupFile}`)

  // Disable per-worker solo caching so PATCH/GET of singleton models don't
  // race across gunicorn workers during tests.
  console.log('[cache] Disabling server cache for the test run...')
  await disableServerCache()
}
