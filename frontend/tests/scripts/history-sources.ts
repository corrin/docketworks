/**
 * Which test-history CSV corpora an analysis script reads.
 *
 * Default runs read only v2's own frontend/test-history/ (gitignored, written
 * by history-reporter.ts). The v1 corpus is archived outside the repo; passing
 * --include-v1-baseline merges it in, with every row tagged by era so the two
 * populations stay distinguishable. The archive location can be overridden
 * with V1_TEST_HISTORY_DIR. Both corpora share the same CSV columns (v2's
 * history-reporter is the v1 reporter ported unchanged), so era is carried as
 * a tag on parsed rows rather than a file-format difference.
 */
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))

export const INCLUDE_V1_FLAG = '--include-v1-baseline'
export const DEFAULT_V1_TEST_HISTORY_DIR = '/home/corrin/docketworks-v1-archive/test-history'

export type Era = 'v1' | 'v2'

export interface HistorySource {
  era: Era
  path: string
}

export function v2HistoryDir(): string {
  return path.resolve(scriptDir, '..', '..', 'test-history')
}

function v1HistoryDir(): string {
  return process.env.V1_TEST_HISTORY_DIR || DEFAULT_V1_TEST_HISTORY_DIR
}

/**
 * Resolve the ordered corpora for one history file (e.g. "test-runs.csv").
 *
 * `explicitInput` (a CLI-provided path) always wins and is treated as v2-era;
 * it exists so ad-hoc "analyze this one file" invocations keep working. The
 * v1 baseline, being explicitly requested, must exist — a missing archive is
 * an error, never a silent exclusion.
 */
export function resolveHistorySources(
  fileName: string,
  includeV1: boolean,
  explicitInput?: string,
): HistorySource[] {
  const sources: HistorySource[] = []

  if (includeV1) {
    const v1Path = path.join(v1HistoryDir(), fileName)
    if (!fs.existsSync(v1Path)) {
      throw new Error(
        `${INCLUDE_V1_FLAG} was passed but the v1 baseline is missing: ${v1Path} ` +
          '(set V1_TEST_HISTORY_DIR to the archive location)',
      )
    }
    sources.push({ era: 'v1', path: v1Path })
  }

  const v2Path = explicitInput
    ? path.resolve(process.cwd(), explicitInput)
    : path.join(v2HistoryDir(), fileName)
  sources.push({ era: 'v2', path: v2Path })

  return sources
}
