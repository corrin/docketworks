import { spawnSync } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'
import * as fs from 'fs'
import os from 'os'
import AdmZip from 'adm-zip'
import { getBackupsDir, getDbConfig } from './db-backup-utils'

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
  const backupDir = getBackupsDir()
  const latestBackupPath = path.join(backupDir, '.latest_backup')

  if (!fs.existsSync(latestBackupPath)) {
    console.warn('[db] No backup found. Skipping restore.')
    return
  }

  const backupFile = fs.readFileSync(latestBackupPath, 'utf8').trim()
  if (!backupFile || !fs.existsSync(backupFile)) {
    console.warn(`[db] Backup file not found: ${backupFile}. Skipping restore.`)
    return
  }

  const inputFd = fs.openSync(backupFile, 'r')
  const result = spawnSync(
    'mysql',
    [
      '-h',
      dbConfig.host,
      '-P',
      dbConfig.port,
      '-u',
      dbConfig.user,
      `-p${dbConfig.password}`,
      dbConfig.database,
    ],
    { stdio: [inputFd, 'inherit', 'inherit'] },
  )
  fs.closeSync(inputFd)

  if (result.status !== 0) {
    throw new Error(`Database restore failed (exit code ${result.status}).`)
  }

  console.log('[db] Database restored successfully.')
}

export default async function globalTeardown() {
  try {
    collectAndAppendTimings()
  } catch (e) {
    console.error('Failed to collect timing data:', e)
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
