/**
 * Analyze network traffic data from the aggregate CSV
 *
 * Usage: npx tsx tests/scripts/analyze-network.ts [network-aggregate.csv]
 */

import * as fs from 'fs'

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
  const lines = content.trim().split('\n')
  const rows: NetworkRow[] = []

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i]
    if (!line.trim()) continue

    const match = line.match(/^([^,]+),([^,]+),"([^"]+)",([^,]+),"([^"]+)",(\d+),(\d+),([\d.]+)/)
    if (!match) continue

    const [, runId, runDate, testName, method, url, status, sizeBytes] = match

    rows.push({
      runId,
      runDate,
      testName,
      method,
      url,
      status: parseInt(status, 10),
      sizeBytes: parseInt(sizeBytes, 10),
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
    if (!byEndpoint.has(key)) byEndpoint.set(key, [])
    byEndpoint.get(key)!.push(row.sizeBytes)
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

console.log(`\n📡 Network Traffic Analysis`)
console.log(`   Source: ${inputFile}`)
console.log(`   Total requests: ${rows.length}`)

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

// Sort by average size descending
stats.sort((a, b) => b.avgSizeKB - a.avgSizeKB)

console.log(`\n📊 All Endpoints (by average size):`)
console.log('─'.repeat(100))
console.log(
  `${'Endpoint'.padEnd(55)} ${'Count'.padStart(6)} ${'Avg'.padStart(10)} ${'Max'.padStart(10)} ${'Total'.padStart(10)}`,
)
console.log('─'.repeat(100))

for (const s of stats) {
  const endpointTrunc = s.endpoint.length > 53 ? s.endpoint.substring(0, 50) + '...' : s.endpoint
  console.log(
    `${endpointTrunc.padEnd(55)} ${String(s.count).padStart(6)} ${formatKB(s.avgSizeKB).padStart(10)} ${formatKB(s.maxSizeKB).padStart(10)} ${formatKB(s.totalMB * 1024).padStart(10)}`,
  )
}

// Issues section
console.log(`\n⚠️  Potential Issues`)
console.log('─'.repeat(100))

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
  console.log('   All URLs are local (good!)')
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
console.log(`\n📈 Summary`)
console.log('─'.repeat(100))
console.log(`   Total requests: ${rows.length}`)
console.log(`   Unique endpoints: ${stats.length}`)
console.log(`   Total data transferred: ${formatKB(totalBytes / 1024)}`)
