/**
 * Render per-test duration plots (raw + moving average) from E2E history.
 *
 * Ported from v1 (tests/scripts/analyze-e2e-trends.ts). Adaptation: reads
 * v2's own test-history/ by default; --include-v1-baseline merges the
 * archived v1 corpus in (see history-sources.ts), with every row tagged by
 * era and the era shown in each point's hover label.
 */
import * as fs from 'fs'
import * as path from 'path'
import { parseCliArgs } from './cli'
import { parseTestRunHistory, type TestRunRow } from './csv'
import {
  INCLUDE_V1_FLAG,
  resolveHistorySources,
  v2HistoryDir,
  type Era,
  type HistorySource,
} from './history-sources'

const defaultOutput = path.join(v2HistoryDir(), 'e2e-per-test-plots.html')

interface TestPoint {
  x: number
  era: Era
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

function parseOptions(): {
  input: string | undefined
  output: string
  minObservations: number
  window: number
  includeV1: boolean
} {
  // parseArgs option names carry no leading dashes.
  const includeV1Option = INCLUDE_V1_FLAG.slice(2)
  const cli = parseCliArgs({
    options: {
      input: { type: 'string' },
      output: { type: 'string' },
      'min-observations': { type: 'string' },
      window: { type: 'string' },
      [includeV1Option]: { type: 'boolean' },
    },
    usage: [
      'Usage: npx tsx tests/scripts/analyze-e2e-trends.ts [options]',
      '',
      'Options:',
      '  --input <path>             CSV to read (default: test-history/test-runs.csv)',
      '  --output <path>            HTML report path (default: test-history/e2e-per-test-plots.html)',
      '  --min-observations <n>     Minimum observations per test (default: 3)',
      '  --window <n>               Early/recent rolling window size (default: 5)',
      `  ${INCLUDE_V1_FLAG}      Merge the archived v1 corpus in (V1_TEST_HISTORY_DIR)`,
    ].join('\n'),
  })

  const outputFlag = cli.stringFlag('output')
  return {
    input: cli.stringFlag('input'),
    output: outputFlag === undefined ? defaultOutput : path.resolve(process.cwd(), outputFlag),
    minObservations: cli.integerFlag('min-observations', 3),
    window: cli.integerFlag('window', 5),
    includeV1: cli.booleanFlag(includeV1Option),
  }
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function average(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = values.toSorted((a, b) => a - b)
  const midpoint = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[midpoint] ?? 0
  return ((sorted[midpoint - 1] ?? 0) + (sorted[midpoint] ?? 0)) / 2
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
    y: averageValues[index] ?? point.durationMs,
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
      const label = `${point.era} | ${point.date} | ${formatMs(point.durationMs)} | ${point.gitSha.slice(0, 8)} | ${point.status}`
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
  const orderedRuns = [...runDates.keys()].toSorted((left, right) =>
    (runDates.get(left) || '').localeCompare(runDates.get(right) || ''),
  )
  const runIndex = new Map(orderedRuns.map((runId, index) => [runId, index]))
  const byTest = new Map<string, TestPoint[]>()

  for (const row of rows) {
    const key = `${row.testFile}\u0000${row.testPath}`
    const points = byTest.get(key) || []
    points.push({
      x: runIndex.get(row.runId) || 0,
      era: row.era,
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
      .toSorted(([left], [right]) => left - right)
      .flatMap(([, runPoints]) => {
        const first = runPoints[0]
        if (!first) return []
        return [
          {
            ...first,
            durationMs: average(runPoints.map((point) => point.durationMs)),
          },
        ]
      })
    if (compact.length < minObservations) continue

    const [testFile = '', testPath = ''] = key.split('\u0000')
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
    metrics: metrics.toSorted((left, right) => right.deltaMs - left.deltaMs),
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
  <p class="legend">Hover points for era, run date, duration, SHA, and status. Tests need at least ${minObservations} observations to be plotted. ${distinctTestCount} distinct test identities were found.</p>
  ${cards}
</body>
</html>`
}

const options = parseOptions()
const sources: HistorySource[] = resolveHistorySources(
  'test-runs.csv',
  options.includeV1,
  options.input,
)
for (const source of sources) {
  if (!fs.existsSync(source.path)) {
    console.error(`File not found: ${source.path}`)
    console.log('Run E2E tests first, or pass --input <path> to an existing test-runs.csv.')
    process.exit(1)
  }
}

const rows = sources.flatMap((source) =>
  parseTestRunHistory(fs.readFileSync(source.path, 'utf8'), source.era),
)
const { metrics, runCount, distinctTestCount } = buildMetrics(
  rows,
  options.minObservations,
  options.window,
)
const sourceDescription = sources.map((source) => `${source.era}: ${source.path}`).join('; ')
const report = renderReport(
  metrics,
  sourceDescription,
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
  .toSorted((left, right) => left.deltaMs - right.deltaMs)
  .filter((item) => item.deltaMs < 0)
  .slice(0, 10)) {
  console.log(
    `  ${formatMs(metric.deltaMs)} ${metric.percentDelta.toFixed(1)}% ${metric.testFile} > ${metric.testPath}`,
  )
}
