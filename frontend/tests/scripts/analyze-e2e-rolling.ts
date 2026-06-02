/**
 * Analyze Playwright E2E timing history with per-test rolling averages.
 *
 * Each test builds its own rolling baseline from its previous observations,
 * so partial E2E runs and newly-added tests do not distort the comparison.
 *
 * Usage:
 *   npx tsx tests/scripts/analyze-e2e-rolling.ts
 *   npx tsx tests/scripts/analyze-e2e-rolling.ts test-history/test-runs.csv
 *   npx tsx tests/scripts/analyze-e2e-rolling.ts --window=5 --min-observations=6
 */

import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const defaultInput = path.resolve(__dirname, '..', '..', 'test-history', 'test-runs.csv')
const defaultOutput = path.resolve(
  __dirname,
  '..',
  '..',
  'test-history',
  'e2e-rolling-performance-analysis.html',
)
const VALID_STATUSES = new Set(['passed', 'perf-fail'])

interface TestRunRow {
  runId: string
  runDate: string
  gitSha: string
  testFile: string
  testPath: string
  durationMs: number
  status: string
}

interface Observation extends TestRunRow {
  observedIndex: number
  previousAverageMs: number | null
  rollingAverageMs: number
  rollingDeltaMs: number | null
  longTermDeltaMs: number | null
  longTermDeltaPct: number | null
  observationCount: number
}

interface TestSeries {
  key: string
  testFile: string
  testPath: string
  observations: Observation[]
}

interface RankingRow {
  testFile: string
  testPath: string
  gitSha: string
  runDate: string
  latestDurationMs: number
  rollingAverageMs: number
  previousAverageMs: number
  rollingDeltaMs: number
  longTermDeltaMs: number
  longTermDeltaPct: number
  observationCount: number
}

function parseCsvLine(line: string): string[] {
  const fields: string[] = []
  let current = ''
  let inQuotes = false

  for (let index = 0; index < line.length; index++) {
    const char = line[index]
    if (char === '"') {
      if (inQuotes && line[index + 1] === '"') {
        current += '"'
        index += 1
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
  return fields
}

function parseCsv(content: string): TestRunRow[] {
  const lines = content
    .replace(/\r/g, '')
    .split('\n')
    .filter((line) => line.trim())
  if (lines.length === 0) return []

  const header = parseCsvLine(lines[0])
  const rows: TestRunRow[] = []

  for (const line of lines.slice(1)) {
    const fields = parseCsvLine(line)
    const row: Record<string, string> = {}
    for (const [index, name] of header.entries()) {
      row[name] = fields[index] || ''
    }

    const status = row.status || ''
    if (!VALID_STATUSES.has(status)) continue

    const durationMs = Number.parseInt((row.duration_ms || '').trim(), 10)
    if (!Number.isFinite(durationMs)) continue

    rows.push({
      runId: row.run_id || '',
      runDate: row.run_date || '',
      gitSha: row.git_sha || '',
      testFile: row.test_file || '',
      testPath: row.test_path || '',
      durationMs,
      status,
    })
  }

  return rows.sort((left, right) => left.runDate.localeCompare(right.runDate))
}

function mean(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length
}

function percentage(delta: number, baseline: number): number {
  return baseline === 0 ? 0 : (delta / baseline) * 100
}

function formatDuration(ms: number): string {
  const sign = ms < 0 ? '-' : ''
  const absolute = Math.abs(ms)
  const seconds = absolute / 1000
  if (seconds < 60) return `${sign}${seconds.toFixed(1)}s`
  return `${sign}${(seconds / 60).toFixed(1)}m`
}

function csvEscape(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

function htmlEscape(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function buildSeries(rows: TestRunRow[], windowSize: number): TestSeries[] {
  const grouped = new Map<string, TestRunRow[]>()
  for (const row of rows) {
    const key = `${row.testFile}\u0000${row.testPath}`
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key)!.push(row)
  }

  const series: TestSeries[] = []
  for (const [key, testRows] of grouped) {
    const durations: number[] = []
    const observations: Observation[] = []

    for (const [index, row] of testRows.entries()) {
      const previousWindow = durations.slice(-windowSize)
      durations.push(row.durationMs)
      const currentWindow = durations.slice(-windowSize)
      const previousAverageMs = previousWindow.length === windowSize ? mean(previousWindow) : null
      const rollingAverageMs = mean(currentWindow)
      const firstWindow = durations.length >= windowSize ? durations.slice(0, windowSize) : []
      const firstAverageMs = firstWindow.length === windowSize ? mean(firstWindow) : null
      const longTermDeltaMs = firstAverageMs === null ? null : rollingAverageMs - firstAverageMs

      observations.push({
        ...row,
        observedIndex: index,
        previousAverageMs,
        rollingAverageMs,
        rollingDeltaMs: previousAverageMs === null ? null : rollingAverageMs - previousAverageMs,
        longTermDeltaMs,
        longTermDeltaPct:
          longTermDeltaMs === null || firstAverageMs === null
            ? null
            : percentage(longTermDeltaMs, firstAverageMs),
        observationCount: durations.length,
      })
    }

    series.push({
      key,
      testFile: testRows[0]?.testFile || '',
      testPath: testRows[0]?.testPath || '',
      observations,
    })
  }

  return series.sort((left, right) => left.key.localeCompare(right.key))
}

function latestRankings(series: TestSeries[], minObservations: number): RankingRow[] {
  const rows: RankingRow[] = []
  for (const item of series) {
    const latest = item.observations[item.observations.length - 1]
    if (
      !latest ||
      latest.previousAverageMs === null ||
      latest.rollingDeltaMs === null ||
      latest.longTermDeltaMs === null ||
      latest.longTermDeltaPct === null ||
      latest.observationCount < minObservations
    ) {
      continue
    }

    rows.push({
      testFile: item.testFile,
      testPath: item.testPath,
      gitSha: latest.gitSha,
      runDate: latest.runDate,
      latestDurationMs: latest.durationMs,
      rollingAverageMs: latest.rollingAverageMs,
      previousAverageMs: latest.previousAverageMs,
      rollingDeltaMs: latest.rollingDeltaMs,
      longTermDeltaMs: latest.longTermDeltaMs,
      longTermDeltaPct: latest.longTermDeltaPct,
      observationCount: latest.observationCount,
    })
  }
  return rows
}

function renderTable(rows: RankingRow[], limit: number): string {
  return rows
    .slice(0, limit)
    .map((row) => {
      const className = row.rollingDeltaMs > 0 ? 'slow' : 'fast'
      return (
        `<tr class="${className}">` +
        `<td>${htmlEscape(row.testFile)}</td>` +
        `<td>${htmlEscape(row.testPath)}</td>` +
        `<td>${row.observationCount}</td>` +
        `<td>${formatDuration(row.previousAverageMs)}</td>` +
        `<td>${formatDuration(row.rollingAverageMs)}</td>` +
        `<td>${formatDuration(row.rollingDeltaMs)}</td>` +
        `<td>${formatDuration(row.longTermDeltaMs)}</td>` +
        `<td>${row.longTermDeltaPct.toFixed(1)}%</td>` +
        `<td>${htmlEscape(row.gitSha.slice(0, 12))}</td>` +
        `</tr>`
      )
    })
    .join('\n')
}

function renderBars(rows: RankingRow[], title: string, limit: number): string {
  const data = rows.slice(0, limit)
  if (data.length === 0) return ''

  const width = 1120
  const labelWidth = 640
  const chartWidth = 330
  const rowHeight = 28
  const height = 64 + data.length * rowHeight
  const maxAbs = Math.max(...data.map((row) => Math.abs(row.rollingDeltaMs)), 1)
  const scale = chartWidth / 2 / maxAbs
  const origin = labelWidth + chartWidth / 2
  let y = 44

  const parts = [
    `<svg viewBox="0 0 ${width} ${height}">`,
    `<text x="0" y="20" class="chart-title">${htmlEscape(title)}</text>`,
    `<line x1="${origin}" y1="30" x2="${origin}" y2="${height - 12}" stroke="#6b7280" />`,
  ]

  for (const row of data) {
    const delta = row.rollingDeltaMs
    const barWidth = Math.abs(delta) * scale
    const x = delta >= 0 ? origin : origin - barWidth
    const color = delta >= 0 ? '#c2410c' : '#15803d'
    const rawLabel = `${row.testFile} > ${row.testPath}`
    const label = rawLabel.length > 92 ? `${rawLabel.slice(0, 89)}...` : rawLabel
    parts.push(
      `<text x="0" y="${y + 15}" class="chart-label">${htmlEscape(label)}</text>`,
      `<rect x="${x}" y="${y}" width="${barWidth}" height="18" rx="3" fill="${color}" />`,
      `<text x="${labelWidth + chartWidth + 12}" y="${y + 15}" class="chart-value">${formatDuration(delta)}</text>`,
    )
    y += rowHeight
  }

  parts.push('</svg>')
  return parts.join('\n')
}

function renderHtml(
  inputPath: string,
  rows: TestRunRow[],
  series: TestSeries[],
  regressions: RankingRow[],
  improvements: RankingRow[],
  windowSize: number,
  minObservations: number,
): string {
  const runIds = new Set(rows.map((row) => row.runId))
  const latestDate = rows[rows.length - 1]?.runDate || ''

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>E2E Rolling Average Performance</title>
  <style>
    body { font-family: Inter, system-ui, sans-serif; margin: 32px; color: #111827; }
    .muted { color: #6b7280; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 22px 0; }
    .card { border: 1px solid #d1d5db; border-radius: 8px; padding: 16px; }
    .metric { font-size: 28px; font-weight: 700; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 14px 0 28px; }
    th, td { border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }
    th { background: #f9fafb; }
    tr.slow td:nth-child(6), tr.slow td:nth-child(7), tr.slow td:nth-child(8) { color: #c2410c; font-weight: 600; }
    tr.fast td:nth-child(6), tr.fast td:nth-child(7), tr.fast td:nth-child(8) { color: #15803d; font-weight: 600; }
    svg { width: 100%; height: auto; margin: 16px 0 28px; }
    .chart-title { font-size: 18px; font-weight: 700; }
    .chart-label { font-size: 12px; fill: #111827; }
    .chart-value { font-size: 12px; fill: #374151; }
  </style>
</head>
<body>
  <h1>E2E Rolling Average Performance</h1>
  <p class="muted">Generated from ${htmlEscape(inputPath)}. Latest observation date: ${htmlEscape(latestDate)}.</p>
  <div class="grid">
    <div class="card"><h2>Runs</h2><div class="metric">${runIds.size}</div></div>
    <div class="card"><h2>Tests</h2><div class="metric">${series.length}</div></div>
    <div class="card"><h2>Window</h2><div class="metric">${windowSize}</div><p class="muted">Minimum observations: ${minObservations}</p></div>
  </div>
  ${renderBars(regressions, 'Largest latest rolling-average regressions', 25)}
  ${renderBars(improvements, 'Largest latest rolling-average improvements', 25)}
  <h2>Latest rolling-average regressions</h2>
  <table>
    <thead><tr><th>File</th><th>Test</th><th>n</th><th>Previous avg</th><th>Latest avg</th><th>Latest delta</th><th>Since first avg</th><th>Since first %</th><th>Latest SHA</th></tr></thead>
    <tbody>${renderTable(regressions, 50)}</tbody>
  </table>
  <h2>Latest rolling-average improvements</h2>
  <table>
    <thead><tr><th>File</th><th>Test</th><th>n</th><th>Previous avg</th><th>Latest avg</th><th>Latest delta</th><th>Since first avg</th><th>Since first %</th><th>Latest SHA</th></tr></thead>
    <tbody>${renderTable(improvements, 50)}</tbody>
  </table>
</body>
</html>`
}

function writeCsv(rows: RankingRow[], outputPath: string): void {
  const header = [
    'test_file',
    'test_path',
    'observations',
    'latest_run_date',
    'latest_git_sha',
    'latest_duration_ms',
    'previous_rolling_avg_ms',
    'latest_rolling_avg_ms',
    'latest_rolling_delta_ms',
    'long_term_delta_ms',
    'long_term_delta_pct',
  ]
  const body = rows.map((row) =>
    [
      csvEscape(row.testFile),
      csvEscape(row.testPath),
      row.observationCount,
      row.runDate,
      row.gitSha,
      Math.round(row.latestDurationMs),
      Math.round(row.previousAverageMs),
      Math.round(row.rollingAverageMs),
      Math.round(row.rollingDeltaMs),
      Math.round(row.longTermDeltaMs),
      row.longTermDeltaPct.toFixed(3),
    ].join(','),
  )
  fs.writeFileSync(outputPath, `${header.join(',')}\n${body.join('\n')}\n`)
}

const args = process.argv.slice(2)
const windowArg = args.find((arg) => arg.startsWith('--window='))
const minArg = args.find((arg) => arg.startsWith('--min-observations='))
const outputArg = args.find((arg) => arg.startsWith('--output='))
const csvArg = args.find((arg) => arg.startsWith('--csv='))
const inputArg = args.find((arg) => !arg.startsWith('--'))
const windowSize = Number.parseInt(windowArg?.split('=')[1] || '5', 10)
const minObservations = Number.parseInt(minArg?.split('=')[1] || String(windowSize + 1), 10)
const inputPath = path.resolve(process.cwd(), inputArg || defaultInput)
const outputPath = path.resolve(process.cwd(), outputArg?.split('=')[1] || defaultOutput)
const csvOutputPath = path.resolve(
  process.cwd(),
  csvArg?.split('=')[1] ||
    path.join(path.dirname(outputPath), 'e2e-rolling-performance-analysis.csv'),
)

if (!fs.existsSync(inputPath)) {
  console.error(`File not found: ${inputPath}`)
  process.exit(1)
}

const rows = parseCsv(fs.readFileSync(inputPath, 'utf8'))
const series = buildSeries(rows, windowSize)
const rankings = latestRankings(series, minObservations)
const regressions = [...rankings].sort((left, right) => right.rollingDeltaMs - left.rollingDeltaMs)
const improvements = [...rankings].sort((left, right) => left.rollingDeltaMs - right.rollingDeltaMs)

fs.mkdirSync(path.dirname(outputPath), { recursive: true })
fs.writeFileSync(
  outputPath,
  renderHtml(inputPath, rows, series, regressions, improvements, windowSize, minObservations),
)
writeCsv(regressions, csvOutputPath)

console.log(`[e2e-rolling] Rows: ${rows.length}`)
console.log(`[e2e-rolling] Tests: ${series.length}`)
console.log(`[e2e-rolling] Ranked tests: ${rankings.length}`)
console.log(`[e2e-rolling] HTML: ${outputPath}`)
console.log(`[e2e-rolling] CSV: ${csvOutputPath}`)
console.log('[e2e-rolling] Largest regressions:')
for (const row of regressions.slice(0, 10)) {
  console.log(`${formatDuration(row.rollingDeltaMs).padStart(8)} ${row.testFile} > ${row.testPath}`)
}
console.log('[e2e-rolling] Largest improvements:')
for (const row of improvements.slice(0, 10)) {
  console.log(`${formatDuration(row.rollingDeltaMs).padStart(8)} ${row.testFile} > ${row.testPath}`)
}
