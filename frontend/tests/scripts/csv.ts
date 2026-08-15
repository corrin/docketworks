/**
 * The one CSV implementation for the test-history corpus and its analyzers.
 *
 * Parsing and quoting used to live as per-script copies, which let two
 * incompatible quoting rules coexist: history-reporter always quoted while
 * backfill-e2e-git-metadata quoted conditionally, and both write the same
 * test-runs.csv — so the corpus mixed styles depending on which tool touched
 * a row last. One module, one rule.
 */
import type { Era } from './history-sources'

/** Split one CSV line into fields, honouring quoted fields and "" escapes. */
export function parseCsvLine(line: string): string[] {
  const fields: string[] = []
  let current = ''
  let inQuotes = false

  for (let index = 0; index < line.length; index += 1) {
    const char = line.charAt(index)
    if (char === '"') {
      if (inQuotes && line.charAt(index + 1) === '"') {
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

/**
 * Render one CSV cell. Minimal quoting, not always-quoting: both are valid
 * CSV, but the corpus is append-then-rewrite (history-reporter appends,
 * backfill rewrites), so the two writers must share one rule and minimal
 * quoting is the stable fixed point a rewrite converges to.
 */
export function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/**
 * Parse CSV content into header-keyed records. Header-name mapping, never
 * positional: the corpora have grown columns over time (git metadata), so a
 * consumer names the columns it needs and fails loudly when one is missing
 * instead of sniffing field counts.
 */
export function parseRows(content: string, required: string[]): Record<string, string>[] {
  const lines = content
    .replace(/\r/g, '')
    .split('\n')
    .filter((line) => line.trim())
  const headerLine = lines[0]
  if (!headerLine) return []

  const header = parseCsvLine(headerLine)
  const headerSet = new Set(header)
  for (const name of required) {
    if (!headerSet.has(name)) {
      throw new Error(`Missing required CSV column: ${name}`)
    }
  }

  return lines.slice(1).map((line) => {
    const fields = parseCsvLine(line)
    const row: Record<string, string> = {}
    for (const [index, name] of header.entries()) {
      row[name] = fields[index] ?? ''
    }
    return row
  })
}

/**
 * One row of test-runs.csv. `era` is an analysis-time tag from
 * history-sources, not a CSV column — writers never emit it.
 */
export interface TestRunRow {
  era: Era
  runId: string
  runDate: string
  gitSha: string
  gitBranch: string
  gitDirty: string
  gitMetadataSource: string
  testFile: string
  testPath: string
  durationMs: number
  status: string
}

// Analyzers only trend completed-with-a-duration outcomes; failed/timedOut
// rows are in the corpus for flake forensics, not timing baselines.
const ANALYZABLE_STATUSES = new Set(['passed', 'perf-fail'])

/**
 * Parse a test-runs.csv corpus into rows worth trending: analyzable status,
 * finite duration. Rewriting tools (backfill) must NOT use this — it drops
 * rows, and a rewriter that drops rows loses history.
 */
export function parseTestRunHistory(content: string, era: Era): TestRunRow[] {
  const records = parseRows(content, [
    'run_id',
    'run_date',
    'test_file',
    'test_path',
    'duration_ms',
    'status',
  ])

  const rows: TestRunRow[] = []
  for (const record of records) {
    const status = record.status ?? ''
    if (!ANALYZABLE_STATUSES.has(status)) continue

    const durationMs = Number.parseInt((record.duration_ms ?? '').trim(), 10)
    if (!Number.isFinite(durationMs)) continue

    rows.push({
      era,
      runId: record.run_id ?? '',
      runDate: record.run_date ?? '',
      gitSha: record.git_sha ?? '',
      gitBranch: record.git_branch ?? '',
      gitDirty: record.git_dirty ?? '',
      gitMetadataSource: record.git_metadata_source ?? '',
      testFile: record.test_file ?? '',
      testPath: record.test_path ?? '',
      durationMs,
      status,
    })
  }
  return rows
}
