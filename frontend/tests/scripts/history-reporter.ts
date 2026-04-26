import type { Reporter, Suite, FullConfig, FullResult } from '@playwright/test/reporter'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'
import AdmZip from 'adm-zip'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

interface PassedTest {
  file: string
  testPath: string
  durationMs: number
  tracePath?: string
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

function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`
}

function appendCsv(filePath: string, header: string, body: string): void {
  const fd = fs.openSync(filePath, 'a')
  try {
    const needsHeader = fs.fstatSync(fd).size === 0
    fs.writeSync(fd, needsHeader ? header + body : body)
  } finally {
    fs.closeSync(fd)
  }
}

function extractActions(
  traceZipPath: string,
  testName: string,
): Array<{
  type: string
  action: string
  selector: string
  duration: number
  error: string
}> {
  const zip = new AdmZip(traceZipPath)
  const out: Array<{
    type: string
    action: string
    selector: string
    duration: number
    error: string
  }> = []
  for (const entry of zip.getEntries()) {
    if (!entry.entryName.endsWith('.trace')) continue
    try {
      const lines = entry.getData().toString('utf8').split('\n').filter(Boolean)
      const callMap = new Map<string, { start?: TraceEntry; end?: TraceEntry }>()
      for (const line of lines) {
        try {
          const event = JSON.parse(line) as TraceEntry
          if (!event.callId) continue
          if (!callMap.has(event.callId)) callMap.set(event.callId, {})
          const call = callMap.get(event.callId)!
          if (event.type === 'before') call.start = event
          else if (event.type === 'after') call.end = event
        } catch {
          /* skip invalid lines */
        }
      }
      for (const [, call] of callMap) {
        if (!call.start || !call.end) continue
        let action = call.start.title
        if (!action) {
          action =
            call.start.method && call.start.class
              ? `${call.start.class}.${call.start.method}`
              : call.start.method || 'unknown'
        }
        if (call.start.method === 'step' && !call.start.title) continue
        out.push({
          type: call.start.method || 'unknown',
          action,
          selector: call.start.params?.selector || call.start.params?.url || '',
          duration: (call.end.endTime || 0) - (call.start.startTime || 0),
          error: call.end.error?.message || '',
        })
      }
    } catch {
      /* skip on error */
    }
  }
  // testName is recorded with the action so callers can group later.
  void testName
  return out
}

export default class HistoryReporter implements Reporter {
  private rootSuite: Suite | undefined

  onBegin(_config: FullConfig, suite: Suite): void {
    this.rootSuite = suite
  }

  onEnd(_result: FullResult): void {
    if (!this.rootSuite) return

    const historyDir = path.resolve(__dirname, '..', '..', 'test-history')
    const testRunsFile = path.join(historyDir, 'test-runs.csv')
    const actionsFile = path.join(historyDir, 'timing-aggregate.csv')

    const passed: PassedTest[] = []
    const walk = (s: Suite): void => {
      for (const t of s.tests) {
        const result = t.results[t.results.length - 1]
        if (result?.status !== 'passed') continue
        // titlePath: ['', projectName, file, ...describes, testTitle]
        const parts = t.titlePath()
        const file = parts[2] || ''
        const testPath = parts.slice(3).join(' > ')
        const trace = result.attachments.find((a) => a.name === 'trace')
        passed.push({
          file,
          testPath,
          durationMs: result.duration,
          tracePath: trace?.path,
        })
      }
      for (const child of s.suites) walk(child)
    }
    walk(this.rootSuite)

    if (passed.length === 0) {
      console.log('[history] No passing tests in this run; nothing to append.')
      return
    }

    fs.mkdirSync(historyDir, { recursive: true })
    const runId = Math.random().toString(36).substring(2, 10)
    const runDate = new Date().toISOString()

    // Per-test summary — primary artifact for setting timeouts.
    const runsHeader = 'run_id,run_date,test_file,test_path,duration_ms\n'
    const runsRows = passed
      .map((r) =>
        [runId, runDate, csvCell(r.file), csvCell(r.testPath), Math.round(r.durationMs)].join(','),
      )
      .join('\n')
    appendCsv(testRunsFile, runsHeader, runsRows + '\n')

    // Per-action data for deep dives, passing tests only.
    let actionRows: string[] = []
    for (const run of passed) {
      if (!run.tracePath) continue
      let actions: ReturnType<typeof extractActions>
      try {
        actions = extractActions(run.tracePath, run.testPath)
      } catch {
        continue
      }
      for (const a of actions) {
        actionRows.push(
          [
            runId,
            runDate,
            csvCell(run.testPath),
            csvCell(a.type),
            csvCell(a.action),
            csvCell(a.selector),
            Math.round(a.duration),
            csvCell(a.error),
          ].join(','),
        )
      }
    }

    if (actionRows.length > 0) {
      const actionsHeader = 'run_id,run_date,test_name,type,action,selector,duration_ms,error\n'
      appendCsv(actionsFile, actionsHeader, actionRows.join('\n') + '\n')
    }

    console.log(
      `[history] Run ${runId}: ${passed.length} passing tests, ` +
        `${actionRows.length} actions -> ${historyDir}/`,
    )
  }
}
