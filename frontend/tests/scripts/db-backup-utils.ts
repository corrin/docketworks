import { spawnSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export type DbConfig = {
  host: string
  port: string
  database: string
  user: string
  password: string
}

export function parseEnvFile(filePath: string): Record<string, string> {
  const content = fs.readFileSync(filePath, 'utf8')
  const entries = content.split(/\r?\n/)
  const result: Record<string, string> = {}

  entries.forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) return
    const equalsIndex = trimmed.indexOf('=')
    if (equalsIndex === -1) return
    const key = trimmed.slice(0, equalsIndex).trim()
    let value = trimmed.slice(equalsIndex + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    result[key] = value
  })

  return result
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
  return path.join(__dirname, '..', '..')
}

export function getBackupsDir(): string {
  return path.join(__dirname, '..', 'backups')
}

/**
 * Parse the backend .env and return all key-value pairs.
 * Used by Playwright config and test scripts to read APP_DOMAIN, DB creds, etc.
 */
export function getBackendEnv(): Record<string, string> {
  const frontendDir = getFrontendDir()
  const backendEnvPath = resolveBackendEnvPath(frontendDir)
  return parseEnvFile(backendEnvPath)
}

export const TEST_CLIENT_NAME = 'ABC Carpet Cleaning TEST IGNORE'

/** Prefix used for all test-created data. Reset script only deletes items matching this. */
export const TEST_DATA_PREFIX = '[TEST]'

export function getDbConfig(): DbConfig {
  const frontendDir = getFrontendDir()
  const backendEnvPath = resolveBackendEnvPath(frontendDir)
  const backendEnv = parseEnvFile(backendEnvPath)

  const required = ['DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST'] as const
  const missing = required.filter((key) => !backendEnv[key])
  if (missing.length > 0) {
    throw new Error(`Backend .env missing required entries: ${missing.join(', ')}`)
  }

  const isSocket = backendEnv.DB_HOST?.startsWith('/')
  if (!isSocket && !backendEnv.DB_PORT) {
    throw new Error('Backend .env missing required entry: DB_PORT (required for TCP connections)')
  }

  return {
    host: backendEnv.DB_HOST,
    port: backendEnv.DB_PORT,
    database: backendEnv.DB_NAME,
    user: backendEnv.DB_USER,
    password: backendEnv.DB_PASSWORD,
  }
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
  if (result.status !== 0) {
    const stderr = result.stderr?.toString() || ''
    throw new Error(`psql failed (exit code ${result.status}): ${stderr}`)
  }
  return result.stdout?.toString().trim() || ''
}

/**
 * Sync all PostgreSQL sequences to match actual table data.
 * Uses Django's sync_sequences management command which discovers all apps
 * automatically and handles both serial and identity columns.
 */
export function syncSequences(_dbConfig: DbConfig): void {
  const frontendDir = getFrontendDir()
  const backendDir = path.resolve(frontendDir, '..')
  const managePy = path.join(backendDir, 'manage.py')

  const result = spawnSync('python', [managePy, 'sync_sequences'], {
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  if (result.status !== 0) {
    const stderr = result.stderr?.toString() || ''
    throw new Error(`sync_sequences failed (exit code ${result.status}): ${stderr}`)
  }
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

  const singletons = ['workflow_cachestate', 'workflow_companydefaults']
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

  // Smoke query — confirms auth_user is queryable.
  try {
    runPsql(dbConfig, `SELECT 1 FROM auth_user LIMIT 1`)
  } catch (e) {
    issues.push(`auth_user smoke query failed: ${(e as Error).message}`)
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

  // Check for [TEST]-prefixed jobs
  const testJobCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM job_job WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testJobCount) > 0) {
    issues.push(`${testJobCount} test jobs found (names starting with '${TEST_DATA_PREFIX}')`)
  }

  // Check for [TEST]-prefixed contacts
  const testContactCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM client_clientcontact WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testContactCount) > 0) {
    issues.push(
      `${testContactCount} test contacts found (names starting with '${TEST_DATA_PREFIX}')`,
    )
  }

  // Check for [TEST]-prefixed clients
  const testClientCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM client_client WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testClientCount) > 0) {
    issues.push(`${testClientCount} test clients found (names starting with '${TEST_DATA_PREFIX}')`)
  }

  return { clean: issues.length === 0, issues }
}
