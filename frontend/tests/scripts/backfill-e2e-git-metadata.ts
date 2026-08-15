/**
 * Backfill git metadata into Playwright E2E test-runs.csv.
 *
 * Historical rows that predate git metadata get commit attribution inferred
 * from run_date using the newest commit before that timestamp.
 *
 * Ported from v1 (tests/scripts/backfill-e2e-git-metadata.ts). This script
 * REWRITES its input file, so it deliberately has no --include-v1-baseline
 * merge: it operates on exactly one corpus — v2's own test-history/ by
 * default, or an explicit path (which may be a copy of the v1 archive; the
 * inferred SHAs then come from whatever repo the file sits under).
 */

import * as fs from 'fs'
import * as path from 'path'
import { execFileSync } from 'child_process'
import { fileURLToPath } from 'url'
import { csvCell, parseRows, type TestRunRow } from './csv'
import { v2HistoryDir } from './history-sources'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(scriptDir, '..', '..', '..')
const defaultInput = path.join(v2HistoryDir(), 'test-runs.csv')
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

// An unrecognised value in the column means the row's provenance is unknown,
// which is exactly what 'unresolved' records.
function toMetadataSource(value: string): MetadataSource {
  switch (value) {
    case 'git':
    case 'inferred_from_run_date':
    case 'unavailable':
    case 'unresolved':
      return value
    default:
      return 'unresolved'
  }
}

interface BackfillStats {
  rows: number
  runs: Set<string>
  inferredRuns: Set<string>
  unresolvedRuns: Set<string>
  alreadyTaggedRuns: Set<string>
}

// Named-column mapping, not field-count sniffing: legacy pre-git-metadata
// files simply lack the git_* columns in their header, so those fields read
// as empty and the backfill fills them in.
function parseCsv(content: string): TestRunRow[] {
  const required = ['run_id', 'run_date', 'test_file', 'test_path', 'duration_ms', 'status']
  return parseRows(content, required).map((record): TestRunRow => {
    const rawDuration = record.duration_ms ?? ''
    const durationMs = Number.parseInt(rawDuration, 10)
    if (!Number.isFinite(durationMs)) {
      // This script rewrites the corpus in place; a malformed duration must
      // stop the rewrite, not be laundered into "NaN" on disk.
      throw new Error(
        `Row for run ${record.run_id ?? ''} has a non-numeric duration_ms: ${rawDuration}`,
      )
    }
    return {
      // era tags merged analysis populations and is never written back;
      // history-sources treats explicit inputs as v2-era, so this does too.
      era: 'v2',
      runId: record.run_id ?? '',
      runDate: record.run_date ?? '',
      gitSha: record.git_sha ?? '',
      gitBranch: record.git_branch ?? '',
      gitDirty: record.git_dirty || 'unknown',
      gitMetadataSource: toMetadataSource(record.git_metadata_source ?? ''),
      testFile: record.test_file ?? '',
      testPath: record.test_path ?? '',
      durationMs,
      status: record.status ?? '',
    }
  })
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

    let metadata = metadataByDate.get(row.runDate)
    if (!metadata) {
      try {
        const sha = inferSha(row.runDate)
        const branch = inferBranch(sha)
        metadata = {
          sha,
          branch,
          source: sha ? 'inferred_from_run_date' : 'unresolved',
        }
      } catch {
        metadata = {
          sha: '',
          branch: '',
          source: 'unresolved',
        }
      }
      metadataByDate.set(row.runDate, metadata)
    }

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
