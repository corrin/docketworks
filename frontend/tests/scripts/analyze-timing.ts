/**
 * Analyze timing data from the aggregate CSV
 *
 * Usage: npx tsx tests/scripts/analyze-timing.ts [timing-aggregate.csv]
 */

import * as fs from 'fs'
import * as path from 'path'

interface TimingRow {
  runId: string
  runDate: string
  testName: string
  type: string
  action: string
  selector: string
  duration: number
  error: string
}

interface ActionStats {
  action: string
  count: number
  total: number
  min: number
  max: number
  avg: number
  p50: number
  p95: number
  failures: number
}

function parseCsv(content: string): TimingRow[] {
  const lines = content.trim().split('\n')
  const header = lines[0]
  const rows: TimingRow[] = []

  // Simple CSV parser that handles quoted fields
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i]
    if (!line.trim()) continue

    const fields: string[] = []
    let current = ''
    let inQuotes = false

    for (let j = 0; j < line.length; j++) {
      const char = line[j]
      if (char === '"') {
        if (inQuotes && line[j + 1] === '"') {
          current += '"'
          j++
        } else {
          inQuotes = !inQuotes
        }
      } else if (char === ',' && !inQuotes) {
        fields.push(current)
        current = ''
      } else {
        current += char
      }
    }
    fields.push(current)

    if (fields.length >= 8) {
      rows.push({
        runId: fields[0],
        runDate: fields[1],
        testName: fields[2],
        type: fields[3],
        action: fields[4],
        selector: fields[5],
        duration: parseInt(fields[6], 10) || 0,
        error: fields[7],
      })
    }
  }

  return rows
}

function percentile(arr: number[], p: number): number {
  if (arr.length === 0) return 0
  const sorted = [...arr].sort((a, b) => a - b)
  const index = Math.ceil((p / 100) * sorted.length) - 1
  return sorted[Math.max(0, index)]
}

function computeStats(rows: TimingRow[]): ActionStats[] {
  const byAction = new Map<string, TimingRow[]>()

  for (const row of rows) {
    const key = row.action
    if (!byAction.has(key)) byAction.set(key, [])
    byAction.get(key)!.push(row)
  }

  const stats: ActionStats[] = []

  for (const [action, actionRows] of byAction) {
    const durations = actionRows.map((r) => r.duration)
    const failures = actionRows.filter((r) => r.error).length

    stats.push({
      action,
      count: actionRows.length,
      total: durations.reduce((a, b) => a + b, 0),
      min: Math.min(...durations),
      max: Math.max(...durations),
      avg: Math.round(durations.reduce((a, b) => a + b, 0) / durations.length),
      p50: percentile(durations, 50),
      p95: percentile(durations, 95),
      failures,
    })
  }

  return stats
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

// Main
const args = process.argv.slice(2)
const inputFile = args[0] || 'test-results/timing-aggregate.csv'

if (!fs.existsSync(inputFile)) {
  console.error(`File not found: ${inputFile}`)
  console.log('Run some tests first to generate timing data.')
  process.exit(1)
}

const content = fs.readFileSync(inputFile, 'utf8')
const rows = parseCsv(content)

console.log(`\n📊 Timing Analysis`)
console.log(`   Source: ${inputFile}`)
console.log(`   Total rows: ${rows.length}`)

// Unique runs
const runs = new Set(rows.map((r) => r.runId))
console.log(`   Unique runs: ${runs.size}`)

// Date range
const dates = rows.map((r) => new Date(r.runDate)).sort((a, b) => a.getTime() - b.getTime())
if (dates.length > 0) {
  console.log(
    `   Date range: ${dates[0].toISOString().split('T')[0]} to ${dates[dates.length - 1].toISOString().split('T')[0]}`,
  )
}

const stats = computeStats(rows)

// Sort by total time descending
stats.sort((a, b) => b.total - a.total)

console.log(`\n🐢 Slowest Actions (by total time):`)
console.log('─'.repeat(100))
console.log(
  `${'Action'.padEnd(50)} ${'Count'.padStart(6)} ${'Total'.padStart(8)} ${'Avg'.padStart(8)} ${'P50'.padStart(8)} ${'P95'.padStart(8)} ${'Max'.padStart(8)}`,
)
console.log('─'.repeat(100))

for (const s of stats.slice(0, 30)) {
  const actionTrunc = s.action.length > 48 ? s.action.substring(0, 45) + '...' : s.action
  const failMark = s.failures > 0 ? ` [${s.failures}❌]` : ''
  console.log(
    `${(actionTrunc + failMark).padEnd(50)} ${String(s.count).padStart(6)} ${formatMs(s.total).padStart(8)} ${formatMs(s.avg).padStart(8)} ${formatMs(s.p50).padStart(8)} ${formatMs(s.p95).padStart(8)} ${formatMs(s.max).padStart(8)}`,
  )
}

// Sort by average time descending
stats.sort((a, b) => b.avg - a.avg)

console.log(`\n⏱️  Slowest Actions (by average time):`)
console.log('─'.repeat(100))
console.log(
  `${'Action'.padEnd(50)} ${'Count'.padStart(6)} ${'Total'.padStart(8)} ${'Avg'.padStart(8)} ${'P50'.padStart(8)} ${'P95'.padStart(8)} ${'Max'.padStart(8)}`,
)
console.log('─'.repeat(100))

for (const s of stats.slice(0, 30)) {
  const actionTrunc = s.action.length > 48 ? s.action.substring(0, 45) + '...' : s.action
  const failMark = s.failures > 0 ? ` [${s.failures}❌]` : ''
  console.log(
    `${(actionTrunc + failMark).padEnd(50)} ${String(s.count).padStart(6)} ${formatMs(s.total).padStart(8)} ${formatMs(s.avg).padStart(8)} ${formatMs(s.p50).padStart(8)} ${formatMs(s.p95).padStart(8)} ${formatMs(s.max).padStart(8)}`,
  )
}

// Show failures
const failures = rows.filter((r) => r.error)
if (failures.length > 0) {
  console.log(`\n❌ Failed Actions (${failures.length} total):`)
  console.log('─'.repeat(80))
  const failedActions = new Map<string, number>()
  for (const f of failures) {
    failedActions.set(f.action, (failedActions.get(f.action) || 0) + 1)
  }
  for (const [action, count] of [...failedActions.entries()].sort((a, b) => b[1] - a[1])) {
    const actionTrunc = action.length > 60 ? action.substring(0, 57) + '...' : action
    console.log(`  ${String(count).padStart(3)}x  ${actionTrunc}`)
  }
}
