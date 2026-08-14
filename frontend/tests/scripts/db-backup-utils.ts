import { spawnSync } from 'child_process'
import dotenv from 'dotenv'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { assertSpawnSucceeded } from './process-result'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))

export type DbConfig = {
  host: string
  /** Unset for Unix-socket hosts (DB_HOST starting with '/'); required for TCP. */
  port: string | undefined
  database: string
  user: string
  password: string
}

function resolveBackendEnvPath(frontendDir: string): string {
  const backendEnvPath = path.join(frontendDir, '..', '.env')
  if (!fs.existsSync(backendEnvPath)) {
    throw new Error(
      `Backend .env not found at ${backendEnvPath}. ` +
        'Expected at repo root (one level up from frontend/).',
    )
  }
  return backendEnvPath
}

export function getFrontendDir(): string {
  return path.join(scriptDir, '..', '..')
}

export function getBackupsDir(): string {
  // <repoRoot>/restore/e2e — kept outside frontend/ so tooling that walks the
  // frontend tree (bundlers, test collectors) never meets 400+ MB SQL dumps.
  return path.join(scriptDir, '..', '..', '..', 'restore', 'e2e')
}

/** Prefix used for all test-created data. Safety checks only look for this. */
export const TEST_DATA_PREFIX = '[TEST]'

function requireBackendEnvEntry(env: Record<string, string | undefined>, key: string): string {
  const value = env[key]
  if (!value) {
    throw new Error(`Backend .env missing required entry: ${key}`)
  }
  return value
}

/**
 * All entries from the backend .env at the repo root, unparsed into any
 * shape — callers validate the specific keys they need (fail-early at the
 * point of use, where the error message can name the consumer).
 */
export function getBackendEnv(): Record<string, string> {
  const backendEnvPath = resolveBackendEnvPath(getFrontendDir())
  return dotenv.parse(fs.readFileSync(backendEnvPath, 'utf8'))
}

export function getDbConfig(): DbConfig {
  const frontendDir = getFrontendDir()
  const backendEnvPath = resolveBackendEnvPath(frontendDir)
  const backendEnv = dotenv.parse(fs.readFileSync(backendEnvPath, 'utf8'))

  const host = requireBackendEnvEntry(backendEnv, 'DB_HOST')
  const database = requireBackendEnvEntry(backendEnv, 'DB_NAME')
  const user = requireBackendEnvEntry(backendEnv, 'DB_USER')
  const password = requireBackendEnvEntry(backendEnv, 'DB_PASSWORD')

  const isSocket = host.startsWith('/')
  const port = backendEnv.DB_PORT
  if (!isSocket && !port) {
    throw new Error('Backend .env missing required entry: DB_PORT (required for TCP connections)')
  }

  return { host, port, database, user, password }
}

/**
 * Run a SQL query via psql and return stdout.
 * Throws on non-zero exit code.
 */
export function runPsql(dbConfig: DbConfig, sql: string): string {
  const args = ['-h', dbConfig.host]
  if (dbConfig.port) {
    args.push('-p', dbConfig.port)
  }
  args.push('-U', dbConfig.user, dbConfig.database, '-tAc', sql)
  const result = spawnSync('psql', args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PGPASSWORD: dbConfig.password },
  })
  assertSpawnSucceeded('psql query', result)
  return result.stdout?.toString().trim() || ''
}

/**
 * Sync all PostgreSQL sequences to match actual table data.
 * Uses the sync_sequences management command (apps/core) which discovers all
 * apps automatically and handles both serial and identity columns.
 */
export function syncSequences(): void {
  const frontendDir = getFrontendDir()
  const backendDir = path.resolve(frontendDir, '..')

  // Use the repository interpreter directly. Agent shells can run a snap-packaged
  // `uv` without a user systemd session, where `uv run` fails before Python starts.
  const python = path.join(backendDir, '.venv', 'bin', 'python')
  const result = spawnSync(python, ['manage.py', 'sync_sequences'], {
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 120_000,
  })
  assertSpawnSucceeded('sync_sequences', result)
}

export type IntegrityCheckResult = {
  ok: boolean
  issues: string[]
}

/**
 * Verify the DB is structurally sane after a restore.
 * READ-ONLY — four cheap queries. Catches the class of silent damage
 * psql partial-restore leaves behind (duplicated singletons, missing
 * PKs). Callers must treat a non-ok result as "restore failed" and
 * preserve the backup.
 */
export function runIntegrityCheck(
  dbConfig: DbConfig,
  expectedMigrationCount: number | null,
): IntegrityCheckResult {
  const issues: string[] = []

  const singletons = ['workflow_companydefaults']
  for (const t of singletons) {
    const count = parseInt(runPsql(dbConfig, `SELECT COUNT(*) FROM ${t}`), 10)
    if (count !== 1) {
      issues.push(`${t} has ${count} rows (expected 1 for a singleton)`)
    }
  }

  const tablesMissingPk = runPsql(
    dbConfig,
    `SELECT t.table_name FROM information_schema.tables t
     LEFT JOIN information_schema.table_constraints c
       ON c.table_name = t.table_name AND c.table_schema = t.table_schema
          AND c.constraint_type = 'PRIMARY KEY'
     WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
       AND c.constraint_name IS NULL
     ORDER BY t.table_name`,
  )
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  if (tablesMissingPk.length > 0) {
    issues.push(`tables missing PRIMARY KEY: ${tablesMissingPk.join(', ')}`)
  }

  if (expectedMigrationCount !== null) {
    const actual = parseInt(runPsql(dbConfig, `SELECT COUNT(*) FROM django_migrations`), 10)
    if (actual !== expectedMigrationCount) {
      issues.push(`django_migrations count is ${actual} (expected ${expectedMigrationCount})`)
    }
  }

  // Smoke query — confirms accounts_staff (custom user model) is queryable.
  try {
    runPsql(dbConfig, `SELECT 1 FROM accounts_staff LIMIT 1`)
  } catch (e) {
    issues.push(`accounts_staff smoke query failed: ${e instanceof Error ? e.message : String(e)}`)
  }

  return { ok: issues.length === 0, issues }
}

export type SafetyCheckResult = {
  clean: boolean
  issues: string[]
}

/**
 * Check if the database is in a safe state for E2E tests.
 * This is READ-ONLY — it never changes state, only reports issues.
 * Returns issues found (empty = clean).
 */
export function checkSafeToTest(dbConfig: DbConfig): SafetyCheckResult {
  const issues: string[] = []
  const prefix = TEST_DATA_PREFIX.replace("'", "''") // SQL-escape

  const testJobCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM job_job WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testJobCount) > 0) {
    issues.push(`${testJobCount} test jobs found (names starting with '${TEST_DATA_PREFIX}')`)
  }

  const testPersonCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM company_person WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testPersonCount) > 0) {
    issues.push(`${testPersonCount} test people found (names starting with '${TEST_DATA_PREFIX}')`)
  }

  const testCompanyCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM company_company WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testCompanyCount) > 0) {
    issues.push(
      `${testCompanyCount} test companies found (names starting with '${TEST_DATA_PREFIX}')`,
    )
  }

  return { clean: issues.length === 0, issues }
}
