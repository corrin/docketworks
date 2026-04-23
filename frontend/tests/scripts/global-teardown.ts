import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'
import * as fs from 'fs'
import os from 'os'
import AdmZip from 'adm-zip'
import { getBackendEnv, getDbConfig, runPsql, syncSequences } from './db-backup-utils'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

interface TraceAction {
  runId: string
  runDate: string
  testName: string
  type: string
  action: string
  selector?: string
  duration: number
  error?: string
}

interface TraceEntry {
  type: string
  callId?: string
  startTime?: number
  endTime?: number
  title?: string
  method?: string
  class?: string
  params?: { selector?: string; url?: string }
  error?: { message: string }
}

function extractTimingFromTrace(
  traceZipPath: string,
  runId: string,
  runDate: string,
): TraceAction[] {
  const zip = new AdmZip(traceZipPath)
  const actions: TraceAction[] = []
  const testName = path.basename(path.dirname(traceZipPath)).replace(/-chromium$/, '')

  for (const entry of zip.getEntries()) {
    if (entry.entryName.endsWith('.trace')) {
      try {
        const content = entry.getData().toString('utf8')
        const lines = content.split('\n').filter((line: string) => line.trim())
        const callMap = new Map<string, { start?: TraceEntry; end?: TraceEntry }>()

        for (const line of lines) {
          try {
            const event = JSON.parse(line) as TraceEntry
            if (event.callId) {
              if (!callMap.has(event.callId)) callMap.set(event.callId, {})
              const call = callMap.get(event.callId)!
              if (event.type === 'before') call.start = event
              else if (event.type === 'after') call.end = event
            }
          } catch {
            /* skip invalid lines */
          }
        }

        for (const [, call] of callMap) {
          if (call.start && call.end) {
            let actionName = call.start.title
            if (!actionName) {
              actionName =
                call.start.method && call.start.class
                  ? `${call.start.class}.${call.start.method}`
                  : call.start.method || 'unknown'
            }
            if (call.start.method === 'step' && !call.start.title) continue

            actions.push({
              runId,
              runDate,
              testName,
              type: call.start.method || 'unknown',
              action: actionName,
              selector: call.start.params?.selector || call.start.params?.url,
              duration: (call.end.endTime || 0) - (call.start.startTime || 0),
              error: call.end.error?.message,
            })
          }
        }
      } catch {
        /* skip on error */
      }
    }
  }
  return actions
}

function collectAndAppendTimings() {
  const testResultsDir = path.join(__dirname, '..', '..', 'test-results')
  const aggregateFile = path.join(testResultsDir, 'timing-aggregate.csv')

  if (!fs.existsSync(testResultsDir)) return

  const runId = Math.random().toString(36).substring(2, 10)
  const runDate = new Date().toISOString()

  const traces: string[] = []
  for (const entry of fs.readdirSync(testResultsDir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const traceFile = path.join(testResultsDir, entry.name, 'trace.zip')
      if (fs.existsSync(traceFile)) traces.push(traceFile)
    }
  }

  if (traces.length === 0) return

  console.log(`\n[trace] Collecting timing data from ${traces.length} trace(s)...`)

  let allActions: TraceAction[] = []
  for (const trace of traces) {
    allActions = allActions.concat(extractTimingFromTrace(trace, runId, runDate))
  }

  const header = 'run_id,run_date,test_name,type,action,selector,duration_ms,error\n'
  const rows = allActions
    .map((a) =>
      [
        a.runId,
        a.runDate,
        `"${a.testName}"`,
        `"${a.type}"`,
        `"${(a.action || '').replace(/"/g, '""')}"`,
        `"${(a.selector || '').replace(/"/g, '""')}"`,
        Math.round(a.duration),
        `"${(a.error || '').replace(/"/g, '""')}"`,
      ].join(','),
    )
    .join('\n')

  const needsHeader = !fs.existsSync(aggregateFile)
  fs.appendFileSync(aggregateFile, (needsHeader ? header : '') + rows + '\n')

  console.log(`[trace] Run ID: ${runId} | ${allActions.length} actions -> ${aggregateFile}`)
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

  // Save the current Xero token before restore — the backup contains a stale
  // token from when the backup was taken, which will likely have expired.
  console.log('[db] Saving current Xero token...')
  let xeroTokenRow: string | null = null
  try {
    xeroTokenRow = runPsql(dbConfig, `SELECT row_to_json(t) FROM workflow_xerotoken t LIMIT 1`)
  } catch {
    console.warn('[db] Could not read Xero token (table may not exist yet). Skipping.')
  }

  // Restore the database
  console.log('[db] Restoring from backup...')
  const inputFd = fs.openSync(backupFile, 'r')
  const result = spawnSync(
    'psql',
    ['-h', dbConfig.host, '-p', dbConfig.port, '-U', dbConfig.user, dbConfig.database],
    {
      stdio: [inputFd, 'pipe', 'pipe'],
      env: { ...process.env, PGPASSWORD: dbConfig.password },
    },
  )
  fs.closeSync(inputFd)

  const stderr = result.stderr?.toString() || ''
  if (stderr) {
    console.log('[db] psql restore output:', stderr)
  }
  if (result.status !== 0) {
    throw new Error(`Database restore failed (exit code ${result.status})`)
  }

  // Re-inject the saved Xero token so the connection stays live
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

  // Backup has served its purpose — delete it.
  fs.unlinkSync(backupFile)

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
    collectAndAppendTimings()
  } catch (e) {
    console.error('Failed to collect timing data:', e)
  }

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
