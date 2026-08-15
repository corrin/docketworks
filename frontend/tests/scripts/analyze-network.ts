/**
 * Analyze network traffic data from the aggregate CSV
 *
 * Usage: npx tsx tests/scripts/analyze-network.ts [network-aggregate.csv]
 *
 * Ported from v1 (tests/scripts/analyze-network.ts). Adaptations: reads the
 * CSV written by v2's enableNetworkLogging (tests/e2e/helpers.ts) whose size
 * column is wire_size_bytes — parsing is header-aware instead of v1's fixed
 * positional regex, so both v2 and archived v1 files work. No v1-baseline
 * flag: this reads test-results/ (per-run scratch), not the test-history
 * corpus. Emoji decorations replaced with words (repo policy).
 */

import * as fs from 'fs'
import { parseCsvLine, parseRows } from './csv'

interface NetworkRow {
  runId: string
  runDate: string
  testName: string
  method: string
  url: string
  status: number
  sizeBytes: number
}

interface EndpointStats {
  endpoint: string
  count: number
  sizes: number[]
  avgSizeKB: number
  maxSizeKB: number
  minSizeKB: number
  totalMB: number
}

function parseCsv(content: string): NetworkRow[] {
  const headerLine = content.trim().split('\n')[0]
  if (!headerLine) return []

  // v2 writes wire_size_bytes (compressed transfer); the v1 format's column
  // was size_bytes. Either satisfies "bytes on the wire per response".
  const header = new Set(parseCsvLine(headerLine))
  const sizeColumn = header.has('wire_size_bytes') ? 'wire_size_bytes' : 'size_bytes'

  const required = ['run_id', 'run_date', 'test_name', 'method', 'url', 'status', sizeColumn]

  const rows: NetworkRow[] = []
  for (const record of parseRows(content, required)) {
    const status = parseInt(record.status ?? '', 10)
    const sizeBytes = parseInt(record[sizeColumn] ?? '', 10)
    if (!Number.isFinite(status) || !Number.isFinite(sizeBytes)) continue

    rows.push({
      runId: record.run_id ?? '',
      runDate: record.run_date ?? '',
      testName: record.test_name ?? '',
      method: record.method ?? '',
      url: record.url ?? '',
      status,
      sizeBytes,
    })
  }

  return rows
}

function normalizeUrl(url: string): string {
  return url
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '{uuid}')
    .replace(/\?.*$/, '')
}

function computeStats(rows: NetworkRow[]): EndpointStats[] {
  const byEndpoint = new Map<string, number[]>()

  for (const row of rows) {
    const key = row.method + ' ' + normalizeUrl(row.url)
    const bucket = byEndpoint.get(key)
    if (bucket) {
      bucket.push(row.sizeBytes)
    } else {
      byEndpoint.set(key, [row.sizeBytes])
    }
  }

  const stats: EndpointStats[] = []

  for (const [endpoint, sizes] of byEndpoint) {
    const total = sizes.reduce((a, b) => a + b, 0)
    stats.push({
      endpoint,
      count: sizes.length,
      sizes,
      avgSizeKB: total / sizes.length / 1024,
      maxSizeKB: Math.max(...sizes) / 1024,
      minSizeKB: Math.min(...sizes) / 1024,
      totalMB: total / 1024 / 1024,
    })
  }

  return stats
}

function formatKB(kb: number): string {
  if (kb < 1) return `${(kb * 1024).toFixed(0)}B`
  if (kb < 1024) return `${kb.toFixed(1)}KB`
  return `${(kb / 1024).toFixed(2)}MB`
}

// Main
const args = process.argv.slice(2)
const inputFile = args[0] || 'test-results/network-aggregate.csv'

if (!fs.existsSync(inputFile)) {
  console.error(`File not found: ${inputFile}`)
  console.log('Run some tests first to generate network data.')
  process.exit(1)
}

const content = fs.readFileSync(inputFile, 'utf8')
const rows = parseCsv(content)

console.log(`\nNetwork Traffic Analysis`)
console.log(`   Source: ${inputFile}`)
console.log(`   Total requests: ${rows.length}`)

// Unique runs
const runs = new Set(rows.map((r) => r.runId))
console.log(`   Unique runs: ${runs.size}`)

// Date range
const dates = rows.map((r) => new Date(r.runDate)).toSorted((a, b) => a.getTime() - b.getTime())
const firstDate = dates[0]
const lastDate = dates[dates.length - 1]
if (firstDate && lastDate) {
  console.log(
    `   Date range: ${firstDate.toISOString().split('T')[0]} to ${lastDate.toISOString().split('T')[0]}`,
  )
}

const stats = computeStats(rows)

// Sort by average size descending
stats.sort((a, b) => b.avgSizeKB - a.avgSizeKB)

console.log(`\nAll Endpoints (by average size):`)
console.log('-'.repeat(100))
console.log(
  `${'Endpoint'.padEnd(55)} ${'Count'.padStart(6)} ${'Avg'.padStart(10)} ${'Max'.padStart(10)} ${'Total'.padStart(10)}`,
)
console.log('-'.repeat(100))

for (const s of stats) {
  const endpointTrunc = s.endpoint.length > 53 ? s.endpoint.substring(0, 50) + '...' : s.endpoint
  console.log(
    `${endpointTrunc.padEnd(55)} ${String(s.count).padStart(6)} ${formatKB(s.avgSizeKB).padStart(10)} ${formatKB(s.maxSizeKB).padStart(10)} ${formatKB(s.totalMB * 1024).padStart(10)}`,
  )
}

// Issues section
console.log(`\nPotential Issues`)
console.log('-'.repeat(100))

// Large responses (excluding source files)
console.log('\n1. LARGE RESPONSES (>10KB, excluding source files):')
const largeResponses = stats.filter((s) => s.avgSizeKB > 10 && !s.endpoint.includes('/src/'))
if (largeResponses.length === 0) {
  console.log('   None found')
} else {
  for (const r of largeResponses) {
    console.log(`   - ${r.endpoint} (${formatKB(r.avgSizeKB)} avg, ${r.count} calls)`)
  }
}

// External URLs
console.log('\n2. EXTERNAL/REMOTE URLs:')
const allUrls = [...new Set(rows.map((r) => r.url))]
const externalUrls = allUrls.filter(
  (url) =>
    !url.startsWith('/') ||
    url.includes('http://') ||
    url.includes('https://') ||
    url.includes('cdn') ||
    url.includes('googleapis') ||
    url.includes('unpkg') ||
    url.includes('cloudflare'),
)
if (externalUrls.length === 0) {
  console.log('   All URLs are local (good)')
} else {
  for (const url of externalUrls) {
    console.log(`   - ${url}`)
  }
}

// Source files (dev server artifacts)
console.log('\n3. SOURCE FILES (dev server artifacts):')
const sourceFiles = stats.filter((s) => s.endpoint.includes('/src/'))
if (sourceFiles.length === 0) {
  console.log('   None')
} else {
  for (const s of sourceFiles) {
    console.log(`   - ${s.endpoint} (${formatKB(s.avgSizeKB)}, ${s.count} times)`)
  }
}

// Threshold suggestions
console.log('\n4. SUGGESTED THRESHOLDS:')
const apiOnly = stats.filter(
  (s) => !s.endpoint.includes('/src/') && !s.endpoint.includes('/jobs/{uuid}?'),
)
if (apiOnly.length > 0) {
  const maxApiSize = Math.max(...apiOnly.map((s) => s.maxSizeKB))
  console.log(`   - Max API response seen: ${formatKB(maxApiSize)}`)
  console.log(`   - Suggested warn threshold: ${Math.ceil(maxApiSize * 1.5)}KB`)
  console.log(`   - Suggested error threshold: ${Math.ceil(maxApiSize * 2)}KB`)
}

// Summary
const totalBytes = rows.reduce((a, r) => a + r.sizeBytes, 0)
console.log(`\nSummary`)
console.log('-'.repeat(100))
console.log(`   Total requests: ${rows.length}`)
console.log(`   Unique endpoints: ${stats.length}`)
console.log(`   Total data transferred: ${formatKB(totalBytes / 1024)}`)
