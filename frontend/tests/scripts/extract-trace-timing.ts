/**
 * Extract timing data from Playwright trace files into CSV for analysis
 *
 * Usage:
 *   Single trace: npx tsx tests/scripts/extract-trace-timing.ts <trace.zip> [output.csv]
 *   All traces:   npx tsx tests/scripts/extract-trace-timing.ts --all [output.csv]
 */

import * as fs from 'fs'
import * as path from 'path'
import AdmZip from 'adm-zip'

interface TraceAction {
  runId: string
  runDate: string
  testName: string
  type: string
  action: string
  selector?: string
  startTime: number
  endTime: number
  duration: number
  error?: string
}

interface TraceEntry {
  type: string
  callId?: string
  stepId?: string
  parentId?: string
  startTime?: number
  endTime?: number
  title?: string
  method?: string
  class?: string
  params?: {
    selector?: string
    url?: string
    state?: string
    timeout?: number
    value?: string
    info?: string
  }
  error?: {
    message: string
  }
}

function generateRunId(): string {
  return Math.random().toString(36).substring(2, 10)
}

function getRunDate(): string {
  return new Date().toISOString()
}

function extractTestNameFromPath(tracePath: string): string {
  // Extract test name from path like test-results/job-edit-job-settings-edit-job-change-internal-notes-chromium/trace.zip
  const dir = path.dirname(tracePath)
  const testDir = path.basename(dir)
  // Remove -chromium suffix
  return testDir.replace(/-chromium$/, '')
}

function extractTimingFromTrace(
  traceZipPath: string,
  runId: string,
  runDate: string,
): TraceAction[] {
  const zip = new AdmZip(traceZipPath)
  const actions: TraceAction[] = []
  const testName = extractTestNameFromPath(traceZipPath)

  const zipEntries = zip.getEntries()

  for (const entry of zipEntries) {
    if (entry.entryName.endsWith('.trace')) {
      try {
        const content = entry.getData().toString('utf8')
        const lines = content.split('\n').filter((line: string) => line.trim())

        const callMap = new Map<string, { start?: TraceEntry; end?: TraceEntry }>()

        for (const line of lines) {
          try {
            const event = JSON.parse(line) as TraceEntry

            if (event.callId) {
              if (!callMap.has(event.callId)) {
                callMap.set(event.callId, {})
              }
              const call = callMap.get(event.callId)!

              if (event.type === 'before') {
                call.start = event
              } else if (event.type === 'after') {
                call.end = event
              }
            }
          } catch {
            // Skip invalid JSON lines
          }
        }

        // Convert to actions
        for (const [, call] of callMap) {
          if (call.start && call.end) {
            const startTime = call.start.startTime || 0
            const endTime = call.end.endTime || 0

            // Build action name from available fields
            let actionName = call.start.title
            if (!actionName || actionName === 'unknown') {
              // Fallback to method + class for better identification
              if (call.start.method && call.start.class) {
                actionName = `${call.start.class}.${call.start.method}`
              } else {
                actionName = call.start.method || call.start.callId || 'unknown'
              }
            }

            // Skip internal steps without meaningful timing
            if (call.start.method === 'step' && !call.start.title) {
              continue
            }

            actions.push({
              runId,
              runDate,
              testName,
              type: call.start.method || 'unknown',
              action: actionName,
              selector: call.start.params?.selector || call.start.params?.url,
              startTime,
              endTime,
              duration: endTime - startTime,
              error: call.end.error?.message,
            })
          }
        }
      } catch (e) {
        console.error(`Error parsing ${entry.entryName}:`, e)
      }
    }
  }

  return actions.sort((a, b) => a.startTime - b.startTime)
}

function findAllTraces(baseDir: string): string[] {
  const traces: string[] = []

  if (!fs.existsSync(baseDir)) {
    return traces
  }

  const entries = fs.readdirSync(baseDir, { withFileTypes: true })
  for (const entry of entries) {
    if (entry.isDirectory()) {
      const traceFile = path.join(baseDir, entry.name, 'trace.zip')
      if (fs.existsSync(traceFile)) {
        traces.push(traceFile)
      }
    }
  }

  return traces
}

function writeCsv(actions: TraceAction[], outputPath: string, append: boolean = false) {
  const header = 'run_id,run_date,test_name,type,action,selector,duration_ms,error\n'
  const rows = actions
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

  if (append && fs.existsSync(outputPath)) {
    fs.appendFileSync(outputPath, rows + '\n')
  } else {
    fs.writeFileSync(outputPath, header + rows + '\n')
  }
}

function printSummary(actions: TraceAction[]) {
  console.log('\n📊 Timing Summary (slowest 25 actions):')
  const sorted = [...actions].sort((a, b) => b.duration - a.duration)
  for (const action of sorted.slice(0, 25)) {
    const status = action.error ? ' [FAILED]' : ''
    const durationStr = `${Math.round(action.duration)}ms`.padStart(8)
    console.log(`  ${durationStr} - ${action.action}${status}`)
  }
}

// Main
const args = process.argv.slice(2)

if (args.length === 0 || args[0] === '--help') {
  console.log(`Usage:
  Single trace: npx tsx tests/scripts/extract-trace-timing.ts <trace.zip> [output.csv]
  All traces:   npx tsx tests/scripts/extract-trace-timing.ts --all [output.csv]`)
  process.exit(0)
}

const runId = generateRunId()
const runDate = getRunDate()

if (args[0] === '--all') {
  // Process all traces in test-results/
  const outputFile = args[1] || 'test-results/timing-all.csv'
  const testResultsDir = path.join(process.cwd(), 'test-results')
  const traces = findAllTraces(testResultsDir)

  if (traces.length === 0) {
    console.log('No trace files found in test-results/')
    process.exit(0)
  }

  console.log(`\n📁 Processing ${traces.length} trace file(s)...`)
  console.log(`   Run ID: ${runId}`)
  console.log(`   Run Date: ${runDate}`)

  let allActions: TraceAction[] = []
  for (const trace of traces) {
    const actions = extractTimingFromTrace(trace, runId, runDate)
    allActions = allActions.concat(actions)
    console.log(`   ✓ ${path.basename(path.dirname(trace))}: ${actions.length} actions`)
  }

  writeCsv(allActions, outputFile)
  console.log(`\n✅ Written ${allActions.length} total actions to ${outputFile}`)
  printSummary(allActions)
} else {
  // Single trace file
  const traceFile = args[0]
  const outputFile = args[1] || traceFile.replace('.zip', '-timing.csv')

  if (!fs.existsSync(traceFile)) {
    console.error(`Trace file not found: ${traceFile}`)
    process.exit(1)
  }

  console.log(`\n📁 Processing trace file: ${traceFile}`)
  console.log(`   Run ID: ${runId}`)
  console.log(`   Run Date: ${runDate}`)

  const actions = extractTimingFromTrace(traceFile, runId, runDate)
  writeCsv(actions, outputFile)
  console.log(`\n✅ Written ${actions.length} actions to ${outputFile}`)
  printSummary(actions)
}
