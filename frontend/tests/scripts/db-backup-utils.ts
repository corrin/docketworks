import { spawnSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

type DbConfig = {
  host: string
  port: string
  database: string
  user: string
  password: string
}

function parseEnvFile(filePath: string): Record<string, string> {
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
  const frontendEnvPath = path.join(frontendDir, '.env')
  if (!fs.existsSync(frontendEnvPath)) {
    throw new Error('Frontend .env not found. Expected at project root.')
  }

  const frontendEnv = parseEnvFile(frontendEnvPath)
  const backendEnvPathRaw = frontendEnv.BACKEND_ENV_PATH
  if (!backendEnvPathRaw) {
    throw new Error('BACKEND_ENV_PATH not set in frontend .env')
  }

  let backendEnvPath = path.isAbsolute(backendEnvPathRaw)
    ? backendEnvPathRaw
    : path.resolve(frontendDir, backendEnvPathRaw)

  if (!fs.existsSync(backendEnvPath)) {
    throw new Error(`Backend .env not found at ${backendEnvPath}`)
  }

  const stats = fs.statSync(backendEnvPath)
  if (stats.isDirectory()) {
    backendEnvPath = path.join(backendEnvPath, '.env')
  }

  if (!fs.existsSync(backendEnvPath)) {
    throw new Error(`Backend .env not found at ${backendEnvPath}`)
  }

  return backendEnvPath
}

export function getFrontendDir(): string {
  return path.join(__dirname, '..', '..')
}

export function getBackupsDir(): string {
  return path.join(__dirname, '..', 'backups')
}

export const TEST_CLIENT_NAME = 'ABC Carpet Cleaning TEST IGNORE'

/** Prefix used for all test-created data. Reset script only deletes items matching this. */
export const TEST_DATA_PREFIX = '[TEST]'

export function getDbConfig(): DbConfig {
  const frontendDir = getFrontendDir()
  const backendEnvPath = resolveBackendEnvPath(frontendDir)
  const backendEnv = parseEnvFile(backendEnvPath)

  const required = ['DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT'] as const
  const missing = required.filter((key) => !backendEnv[key])
  if (missing.length > 0) {
    throw new Error(`Backend .env missing required entries: ${missing.join(', ')}`)
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
  const result = spawnSync(
    'psql',
    ['-h', dbConfig.host, '-p', dbConfig.port, '-U', dbConfig.user, dbConfig.database, '-tAc', sql],
    {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PGPASSWORD: dbConfig.password },
    },
  )
  if (result.status !== 0) {
    const stderr = result.stderr?.toString() || ''
    throw new Error(`psql failed (exit code ${result.status}): ${stderr}`)
  }
  return result.stdout?.toString().trim() || ''
}

/**
 * Sync all PostgreSQL sequences to match actual table data.
 */
export function syncSequences(dbConfig: DbConfig): void {
  runPsql(
    dbConfig,
    `DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT
            quote_ident(n.nspname) || '.' || quote_ident(c.relname) AS seq_name,
            quote_ident(tn.nspname) || '.' || quote_ident(t.relname) AS table_name,
            quote_ident(a.attname) AS column_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'a'
        JOIN pg_class t ON t.oid = d.refobjid
        JOIN pg_namespace tn ON tn.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE c.relkind = 'S'
    LOOP
        EXECUTE format(
            'SELECT setval(%L, COALESCE((SELECT MAX(%s) FROM %s), 1))',
            r.seq_name, r.column_name, r.table_name
        );
    END LOOP;
END $$;`,
  )
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
    `SELECT COUNT(*) FROM workflow_job WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testJobCount) > 0) {
    issues.push(`${testJobCount} test jobs found (names starting with '${TEST_DATA_PREFIX}')`)
  }

  // Check for [TEST]-prefixed contacts
  const testContactCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM client_contact WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testContactCount) > 0) {
    issues.push(
      `${testContactCount} test contacts found (names starting with '${TEST_DATA_PREFIX}')`,
    )
  }

  // Check for [TEST]-prefixed clients
  const testClientCount = runPsql(
    dbConfig,
    `SELECT COUNT(*) FROM workflow_client WHERE name LIKE '${prefix}%'`,
  )
  if (parseInt(testClientCount) > 0) {
    issues.push(`${testClientCount} test clients found (names starting with '${TEST_DATA_PREFIX}')`)
  }

  return { clean: issues.length === 0, issues }
}
