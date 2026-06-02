import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const defaultInput = path.resolve(__dirname, '..', '..', 'test-history', 'test-runs.csv')
const defaultOutput = path.resolve(__dirname, '..', '..', 'test-history', 'e2e-per-test-plots.html')
const validStatuses = new Set(['passed', 'perf-fail'])

interface TestRunRow {
  runId: string
  runDate: string
  gitSha: string
  testFile: string
  testPath: string
  durationMs: number
  status: string
}

interface TestPoint {
  x: number
  runId: string
  date: string
  durationMs: number
  gitSha: string
  status: string
}

interface TestMetric {
  testFile: string
  testPath: string
  points: TestPoint[]
  observations: number
  earlyAverageMs: number
  recentAverageMs: number
  deltaMs: number
  percentDelta: number
  slopeMsPerRun: number
  minMs: number
  maxMs: number
  medianMs: number
  standardDeviationMs: number
}

interface Options {
  input: string
  output: string
  minObservations: number
  window: number
}

function parseArgs(): Options {
  const args = process.argv.slice(2)
  const options: Options = {
    input: defaultInput,
    output: defaultOutput,
    minObservations: 3,
    window: 5,
  }

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index]
    const next = args[index + 1]
    if (arg === '--input' && next) {
      options.input = path.resolve(process.cwd(), next)
      index += 1
    } else if (arg === '--output' && next) {
      options.output = path.resolve(process.cwd(), next)
      index += 1
    } else if (arg === '--min-observations' && next) {
      options.minObservations = Number.parseInt(next, 10)
      index += 1
    } else if (arg === '--window' && next) {
      options.window = Number.parseInt(next, 10)
      index += 1
    } else if (arg === '--help') {
      console.log(
        [
          'Usage: npx tsx tests/scripts/analyze-e2e-trends.ts [options]',
          '',
          'Options:',
          '  --input <path>             CSV to read (default: test-history/test-runs.csv)',
          '  --output <path>            HTML report path (default: test-history/e2e-per-test-plots.html)',
          '  --min-observations <n>     Minimum observations per test (default: 3)',
          '  --window <n>               Early/recent rolling window size (default: 5)',
        ].join('\n'),
      )
      process.exit(0)
    } else {
      throw new Error(`Unknown argument: ${arg}`)
    }
  }

  return options
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function parseCsvLine(line: string): string[] {
  const fields: string[] = []
  let current = ''
  let inQuotes = false

  for (let index = 0; index < line.length; index += 1) {
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
  const indexByName = new Map(header.map((name, index) => [name, index]))

  const required = ['run_id', 'run_date', 'test_file', 'test_path', 'duration_ms', 'status']
  for (const field of required) {
    if (!indexByName.has(field)) {
      throw new Error(`Missing required CSV column: ${field}`)
    }
  }

  return lines.slice(1).flatMap((line) => {
    const fields = parseCsvLine(line)
    const status = fields[indexByName.get('status')!] || ''
    if (!validStatuses.has(status)) return []

    const durationMs = Number.parseInt(fields[indexByName.get('duration_ms')!] || '', 10)
    if (!Number.isFinite(durationMs)) return []

    return [
      {
        runId: fields[indexByName.get('run_id')!] || '',
        runDate: fields[indexByName.get('run_date')!] || '',
        gitSha: fields[indexByName.get('git_sha') ?? -1] || '',
        testFile: fields[indexByName.get('test_file')!] || '',
        testPath: fields[indexByName.get('test_path')!] || '',
        durationMs,
        status,
      },
    ]
  })
}

function average(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const midpoint = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[midpoint]
  return (sorted[midpoint - 1] + sorted[midpoint]) / 2
}

function standardDeviation(values: number[]): number {
  if (values.length < 2) return 0
  const avg = average(values)
  return Math.sqrt(average(values.map((value) => (value - avg) ** 2)))
}

function percentDelta(delta: number, base: number): number {
  return base === 0 ? 0 : (delta / base) * 100
}

function slope(points: TestPoint[]): number {
  if (points.length < 2) return 0
  const avgX = average(points.map((point) => point.x))
  const avgY = average(points.map((point) => point.durationMs))
  const denominator = points.reduce((total, point) => total + (point.x - avgX) ** 2, 0)
  if (denominator === 0) return 0
  return (
    points.reduce((total, point) => total + (point.x - avgX) * (point.durationMs - avgY), 0) /
    denominator
  )
}

function formatMs(value: number): string {
  const sign = value < 0 ? '-' : ''
  const absValue = Math.abs(value)
  const seconds = absValue / 1000
  if (seconds < 60) return `${sign}${seconds.toFixed(1)}s`
  return `${sign}${(seconds / 60).toFixed(1)}m`
}

function movingAverage(values: number[], window: number): number[] {
  return values.map((_, index) => {
    const start = Math.max(0, index - window + 1)
    return average(values.slice(start, index + 1))
  })
}

function polyline(
  points: Array<{ x: number; y: number }>,
  width: number,
  height: number,
  minX: number,
  maxX: number,
  minY: number,
  maxY: number,
): string {
  if (points.length < 2) return ''
  const xRange = Math.max(maxX - minX, 1)
  const yRange = Math.max(maxY - minY, 1)
  return points
    .map((point) => {
      const x = ((point.x - minX) / xRange) * width
      const y = height - ((point.y - minY) / yRange) * height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function renderChart(points: TestPoint[], title: string, window: number): string {
  const width = 980
  const height = 190
  const paddingLeft = 62
  const paddingRight = 20
  const paddingTop = 18
  const paddingBottom = 34
  const plotWidth = width - paddingLeft - paddingRight
  const plotHeight = height - paddingTop - paddingBottom

  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.durationMs)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  let minY = Math.min(...ys)
  let maxY = Math.max(...ys)
  if (minY === maxY) {
    minY = Math.max(0, minY - 1000)
    maxY += 1000
  }
  const margin = (maxY - minY) * 0.12
  minY = Math.max(0, minY - margin)
  maxY += margin

  const averageValues = movingAverage(ys, window)
  const rawPoints = points.map((point) => ({ x: point.x, y: point.durationMs }))
  const averagePoints = points.map((point, index) => ({
    x: point.x,
    y: averageValues[index],
  }))
  const rawLine = polyline(rawPoints, plotWidth, plotHeight, minX, maxX, minY, maxY)
  const averageLine = polyline(averagePoints, plotWidth, plotHeight, minX, maxX, minY, maxY)
  const yRange = Math.max(maxY - minY, 1)
  const xRange = Math.max(maxX - minX, 1)

  const ticks = [minY, (minY + maxY) / 2, maxY]
    .map((value) => {
      const y = paddingTop + plotHeight - ((value - minY) / yRange) * plotHeight
      return (
        `<line x1="${paddingLeft}" x2="${width - paddingRight}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" class="gridline" />` +
        `<text x="6" y="${(y + 4).toFixed(1)}" class="axis">${escapeHtml(formatMs(value))}</text>`
      )
    })
    .join('')

  const circles = points
    .map((point) => {
      const x = paddingLeft + ((point.x - minX) / xRange) * plotWidth
      const y = paddingTop + plotHeight - ((point.durationMs - minY) / yRange) * plotHeight
      const label = `${point.date} | ${formatMs(point.durationMs)} | ${point.gitSha.slice(0, 8)} | ${point.status}`
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.2" class="point"><title>${escapeHtml(label)}</title></circle>`
    })
    .join('')

  return (
    `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}">` +
    ticks +
    `<line x1="${paddingLeft}" x2="${width - paddingRight}" y1="${paddingTop + plotHeight}" y2="${paddingTop + plotHeight}" class="axis-line" />` +
    `<polyline points="${rawLine}" transform="translate(${paddingLeft},${paddingTop})" class="raw-line" />` +
    `<polyline points="${averageLine}" transform="translate(${paddingLeft},${paddingTop})" class="average-line" />` +
    circles +
    '</svg>'
  )
}

function buildMetrics(
  rows: TestRunRow[],
  minObservations: number,
  window: number,
): {
  metrics: TestMetric[]
  runCount: number
  distinctTestCount: number
} {
  const runDates = new Map<string, string>()
  for (const row of rows) {
    runDates.set(row.runId, row.runDate)
  }
  const orderedRuns = [...runDates.keys()].sort((left, right) =>
    (runDates.get(left) || '').localeCompare(runDates.get(right) || ''),
  )
  const runIndex = new Map(orderedRuns.map((runId, index) => [runId, index]))
  const byTest = new Map<string, TestPoint[]>()

  for (const row of rows) {
    const key = `${row.testFile}\0${row.testPath}`
    const points = byTest.get(key) || []
    points.push({
      x: runIndex.get(row.runId) || 0,
      runId: row.runId,
      date: row.runDate,
      durationMs: row.durationMs,
      gitSha: row.gitSha,
      status: row.status,
    })
    byTest.set(key, points)
  }

  const metrics: TestMetric[] = []
  for (const [key, points] of byTest) {
    const compactByRun = new Map<number, TestPoint[]>()
    for (const point of points) {
      const runPoints = compactByRun.get(point.x) || []
      runPoints.push(point)
      compactByRun.set(point.x, runPoints)
    }

    const compact = [...compactByRun.entries()]
      .sort(([left], [right]) => left - right)
      .map(([, runPoints]) => ({
        ...runPoints[0],
        durationMs: average(runPoints.map((point) => point.durationMs)),
      }))
    if (compact.length < minObservations) continue

    const [testFile = '', testPath = ''] = key.split('\0')
    const early = compact.slice(0, Math.min(window, compact.length))
    const recent = compact.slice(-Math.min(window, compact.length))
    const durations = compact.map((point) => point.durationMs)
    const earlyAverageMs = average(early.map((point) => point.durationMs))
    const recentAverageMs = average(recent.map((point) => point.durationMs))
    const deltaMs = recentAverageMs - earlyAverageMs

    metrics.push({
      testFile,
      testPath,
      points: compact,
      observations: compact.length,
      earlyAverageMs,
      recentAverageMs,
      deltaMs,
      percentDelta: percentDelta(deltaMs, earlyAverageMs),
      slopeMsPerRun: slope(compact),
      minMs: Math.min(...durations),
      maxMs: Math.max(...durations),
      medianMs: median(durations),
      standardDeviationMs: standardDeviation(durations),
    })
  }

  return {
    metrics: metrics.sort((left, right) => right.deltaMs - left.deltaMs),
    runCount: orderedRuns.length,
    distinctTestCount: byTest.size,
  }
}

function renderReport(
  metrics: TestMetric[],
  source: string,
  runCount: number,
  distinctTestCount: number,
  window: number,
  minObservations: number,
): string {
  const slowerCount = metrics.filter((metric) => metric.deltaMs > 0).length
  const fasterCount = metrics.filter((metric) => metric.deltaMs < 0).length
  const cards = metrics
    .map((metric) => {
      const direction = metric.deltaMs > 0 ? 'slower' : 'faster'
      const title = `${metric.testFile} > ${metric.testPath}`
      return (
        `<section class="card ${direction}">` +
        `<h2>${escapeHtml(title)}</h2>` +
        '<div class="stats">' +
        `<span>n=${metric.observations}</span>` +
        `<span>early avg ${formatMs(metric.earlyAverageMs)}</span>` +
        `<span>recent avg ${formatMs(metric.recentAverageMs)}</span>` +
        `<span class="${direction}">delta ${formatMs(metric.deltaMs)} (${metric.percentDelta.toFixed(1)}%)</span>` +
        `<span>slope ${formatMs(metric.slopeMsPerRun)}/run</span>` +
        `<span>median ${formatMs(metric.medianMs)}</span>` +
        `<span>min/max ${formatMs(metric.minMs)}/${formatMs(metric.maxMs)}</span>` +
        `<span>sd ${formatMs(metric.standardDeviationMs)}</span>` +
        '</div>' +
        renderChart(metric.points, title, window) +
        '</section>'
      )
    })
    .join('')

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>E2E Per-Test Timing Plots</title>
  <style>
    body { font-family: Inter, system-ui, sans-serif; margin: 28px; color: #111827; background: #fff; }
    h1 { margin-bottom: 0; }
    .muted { color: #6b7280; }
    .summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 20px 0; }
    .summary div { border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; }
    .summary strong { display: block; font-size: 24px; }
    .card { border: 1px solid #d1d5db; border-radius: 8px; padding: 14px; margin: 16px 0 24px; }
    .card h2 { font-size: 15px; margin: 0 0 10px; }
    .stats { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; font-size: 12px; color: #374151; }
    .stats span { background: #f3f4f6; border-radius: 999px; padding: 4px 8px; }
    .slower { color: #c2410c; }
    .faster { color: #15803d; }
    .chart { width: 100%; height: auto; }
    .gridline { stroke: #e5e7eb; stroke-width: 1; }
    .axis-line { stroke: #9ca3af; stroke-width: 1; }
    .axis { fill: #6b7280; font-size: 11px; }
    .raw-line { fill: none; stroke: #93c5fd; stroke-width: 1.7; opacity: 0.8; }
    .average-line { fill: none; stroke: #1d4ed8; stroke-width: 3; }
    .point { fill: #1d4ed8; opacity: 0.85; }
    .legend { font-size: 13px; margin: 8px 0 18px; }
  </style>
</head>
<body>
  <h1>E2E Per-Test Timing Plots</h1>
  <p class="muted">Generated from ${escapeHtml(source)}. Each chart plots every recorded run for one test. Pale line is raw duration; dark line is trailing ${window}-observation moving average. Tests are sorted by recent average minus early average.</p>
  <div class="summary">
    <div><strong>${metrics.length}</strong>plotted tests</div>
    <div><strong>${slowerCount}</strong>slower by recent average</div>
    <div><strong>${fasterCount}</strong>faster by recent average</div>
    <div><strong>${runCount}</strong>runs in history</div>
  </div>
  <p class="legend">Hover points for run date, duration, SHA, and status. Tests need at least ${minObservations} observations to be plotted. ${distinctTestCount} distinct test identities were found.</p>
  ${cards}
</body>
</html>`
}

const options = parseArgs()
if (!fs.existsSync(options.input)) {
  console.error(`File not found: ${options.input}`)
  console.log('Run E2E tests first, or pass --input <path> to an existing test-runs.csv.')
  process.exit(1)
}

const rows = parseCsv(fs.readFileSync(options.input, 'utf8'))
const { metrics, runCount, distinctTestCount } = buildMetrics(
  rows,
  options.minObservations,
  options.window,
)
const report = renderReport(
  metrics,
  options.input,
  runCount,
  distinctTestCount,
  options.window,
  options.minObservations,
)

fs.mkdirSync(path.dirname(options.output), { recursive: true })
fs.writeFileSync(options.output, report)

console.log(`[e2e-trends] Wrote ${options.output}`)
console.log(
  `[e2e-trends] Plotted ${metrics.length}/${distinctTestCount} tests across ${runCount} runs`,
)
console.log(
  `[e2e-trends] Slower: ${metrics.filter((metric) => metric.deltaMs > 0).length}; faster: ${metrics.filter((metric) => metric.deltaMs < 0).length}`,
)

console.log('[e2e-trends] Top slower tests:')
for (const metric of metrics.filter((item) => item.deltaMs > 0).slice(0, 10)) {
  console.log(
    `  ${formatMs(metric.deltaMs)} ${metric.percentDelta.toFixed(1)}% ${metric.testFile} > ${metric.testPath}`,
  )
}

console.log('[e2e-trends] Top faster tests:')
for (const metric of [...metrics]
  .sort((left, right) => left.deltaMs - right.deltaMs)
  .filter((item) => item.deltaMs < 0)
  .slice(0, 10)) {
  console.log(
    `  ${formatMs(metric.deltaMs)} ${metric.percentDelta.toFixed(1)}% ${metric.testFile} > ${metric.testPath}`,
  )
}
