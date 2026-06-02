/**
 * Backfill git metadata into Playwright E2E test-runs.csv.
 *
 * Existing historical rows predate git metadata, so commit attribution is
 * inferred from run_date using the newest commit before that timestamp.
 */

import * as fs from 'fs'
import * as path from 'path'
import { execFileSync } from 'child_process'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..', '..', '..')
const defaultInput = path.resolve(__dirname, '..', '..', 'test-history', 'test-runs.csv')
const OUTPUT_HEADER = [
  'run_id',
  'run_date',
  'git_sha',
  'git_branch',
  'git_dirty',
  'git_metadata_source',
  'test_file',
  'test_path',
  'duration_ms',
  'status',
]

type MetadataSource = 'git' | 'inferred_from_run_date' | 'unresolved' | 'unavailable'

interface TestRunRow {
  runId: string
  runDate: string
  gitSha: string
  gitBranch: string
  gitDirty: string
  gitMetadataSource: MetadataSource
  testFile: string
  testPath: string
  durationMs: string
  status: string
}

interface BackfillStats {
  rows: number
  runs: Set<string>
  inferredRuns: Set<string>
  unresolvedRuns: Set<string>
  alreadyTaggedRuns: Set<string>
}

function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
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
    if (fields.length === 6 && header.includes('test_file')) {
      rows.push({
        runId: fields[0] || '',
        runDate: fields[1] || '',
        gitSha: '',
        gitBranch: '',
        gitDirty: 'unknown',
        gitMetadataSource: 'unresolved',
        testFile: fields[2] || '',
        testPath: fields[3] || '',
        durationMs: fields[4] || '',
        status: fields[5] || '',
      })
    } else if (fields.length >= 10 && header.includes('git_sha')) {
      rows.push({
        runId: fields[0] || '',
        runDate: fields[1] || '',
        gitSha: fields[2] || '',
        gitBranch: fields[3] || '',
        gitDirty: fields[4] || 'unknown',
        gitMetadataSource: (fields[5] || 'unresolved') as MetadataSource,
        testFile: fields[6] || '',
        testPath: fields[7] || '',
        durationMs: fields[8] || '',
        status: fields[9] || '',
      })
    } else {
      throw new Error(`Unsupported test-runs.csv row shape with ${fields.length} fields`)
    }
  }

  return rows
}

function runGit(args: string[]): string {
  return execFileSync('git', args, {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim()
}

function inferSha(runDate: string): string {
  if (!runDate) return ''
  return runGit(['rev-list', '-1', `--before=${runDate}`, '--all'])
}

function inferBranch(sha: string): string {
  if (!sha) return ''
  const branches = runGit(['branch', '--contains', sha, '--format=%(refname:short)'])
    .split('\n')
    .map((branch) => branch.trim())
    .filter(Boolean)
  return branches.join(';')
}

function backfill(rows: TestRunRow[]): { rows: TestRunRow[]; stats: BackfillStats } {
  const metadataByDate = new Map<string, { sha: string; branch: string; source: MetadataSource }>()
  const stats: BackfillStats = {
    rows: rows.length,
    runs: new Set<string>(),
    inferredRuns: new Set<string>(),
    unresolvedRuns: new Set<string>(),
    alreadyTaggedRuns: new Set<string>(),
  }

  const updatedRows = rows.map((row) => {
    stats.runs.add(row.runId)
    if (row.gitSha) {
      stats.alreadyTaggedRuns.add(row.runId)
      return row
    }

    if (!metadataByDate.has(row.runDate)) {
      try {
        const sha = inferSha(row.runDate)
        const branch = inferBranch(sha)
        metadataByDate.set(row.runDate, {
          sha,
          branch,
          source: sha ? 'inferred_from_run_date' : 'unresolved',
        })
      } catch {
        metadataByDate.set(row.runDate, {
          sha: '',
          branch: '',
          source: 'unresolved',
        })
      }
    }

    const metadata = metadataByDate.get(row.runDate)!
    if (metadata.sha) {
      stats.inferredRuns.add(row.runId)
    } else {
      stats.unresolvedRuns.add(row.runId)
    }

    return {
      ...row,
      gitSha: metadata.sha,
      gitBranch: metadata.branch,
      gitDirty: 'unknown',
      gitMetadataSource: metadata.source,
    }
  })

  return { rows: updatedRows, stats }
}

function renderCsv(rows: TestRunRow[]): string {
  const renderedRows = rows.map((row) =>
    [
      row.runId,
      row.runDate,
      row.gitSha,
      csvCell(row.gitBranch),
      row.gitDirty,
      row.gitMetadataSource,
      csvCell(row.testFile),
      csvCell(row.testPath),
      row.durationMs,
      row.status,
    ].join(','),
  )
  return `${OUTPUT_HEADER.join(',')}\n${renderedRows.join('\n')}\n`
}

function printStats(stats: BackfillStats, target: string, dryRun: boolean): void {
  console.log(`[e2e-history] ${dryRun ? 'Dry run' : 'Backfilled'} ${target}`)
  console.log(`[e2e-history] Rows: ${stats.rows}`)
  console.log(`[e2e-history] Distinct runs: ${stats.runs.size}`)
  console.log(`[e2e-history] Already tagged runs: ${stats.alreadyTaggedRuns.size}`)
  console.log(`[e2e-history] Inferred runs: ${stats.inferredRuns.size}`)
  console.log(`[e2e-history] Unresolved runs: ${stats.unresolvedRuns.size}`)
}

const args = process.argv.slice(2)
const dryRun = args.includes('--dry-run')
const input = args.find((arg) => !arg.startsWith('--')) || defaultInput
const target = path.resolve(process.cwd(), input)

if (!fs.existsSync(target)) {
  console.error(`[e2e-history] File not found: ${target}`)
  process.exit(1)
}

const rows = parseCsv(fs.readFileSync(target, 'utf8'))
const result = backfill(rows)
const output = renderCsv(result.rows)
printStats(result.stats, target, dryRun)

if (!dryRun) {
  fs.writeFileSync(target, output)
}
