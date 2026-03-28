/**
 * E2E Database Reset Script
 *
 * Resets the database to a clean state suitable for E2E tests.
 * This is a deliberate action — run it when tests report the DB is dirty.
 *
 * Usage:
 *   npm run test:e2e:reset           # Dry run — shows what would be deleted
 *   npm run test:e2e:reset -- --confirm  # Actually deletes test data
 *
 * Production safety: uses Django ORM for safe FK cascading, only deletes
 * items with [TEST] prefix or on the designated test client.
 */
import { spawnSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { getBackupsDir, getDbConfig, syncSequences } from './db-backup-utils'

const isConfirmed = process.argv.includes('--confirm')

function formatTimestamp(date: Date): string {
  const pad = (value: number) => value.toString().padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`
}

function resolveManagePyPath(): string {
  // Walk up from frontend/tests/scripts/ to find manage.py
  let dir = path.resolve(__dirname, '..', '..', '..')
  const managePy = path.join(dir, 'manage.py')
  if (!fs.existsSync(managePy)) {
    throw new Error(`manage.py not found at ${managePy}`)
  }
  return managePy
}

function runDjangoCleanup(confirm: boolean): { status: number; output: string } {
  const managePy = resolveManagePyPath()
  const args = [managePy, 'e2e_cleanup']
  if (confirm) args.push('--confirm')

  const result = spawnSync('python', args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    cwd: path.dirname(managePy),
  })

  const stdout = result.stdout?.toString() || ''
  const stderr = result.stderr?.toString() || ''
  const output = stdout + (stderr ? `\n${stderr}` : '')

  return { status: result.status ?? 1, output }
}

function takeBackup(dbConfig: ReturnType<typeof getDbConfig>): void {
  const backupDir = getBackupsDir()
  fs.mkdirSync(backupDir, { recursive: true })

  const backupFile = path.join(backupDir, `backup_${formatTimestamp(new Date())}.sql`)
  console.log(`[reset] Taking clean backup: ${backupFile}`)

  const outputFd = fs.openSync(backupFile, 'w')
  const result = spawnSync(
    'pg_dump',
    ['--clean', '-h', dbConfig.host, '-p', dbConfig.port, '-U', dbConfig.user, dbConfig.database],
    {
      stdio: ['ignore', outputFd, 'inherit'],
      env: { ...process.env, PGPASSWORD: dbConfig.password },
    },
  )
  fs.closeSync(outputFd)

  if (result.status !== 0) {
    throw new Error(`Database backup failed (exit code ${result.status}).`)
  }

  fs.writeFileSync(path.join(backupDir, '.latest_backup'), backupFile, 'utf8')

  // Keep only last 5 backups
  const backups = fs
    .readdirSync(backupDir)
    .filter((name) => name.startsWith('backup_') && name.endsWith('.sql'))
    .map((name) => ({
      path: path.join(backupDir, name),
      mtimeMs: fs.statSync(path.join(backupDir, name)).mtimeMs,
    }))
    .sort((a, b) => b.mtimeMs - a.mtimeMs)

  backups.slice(5).forEach((entry) => {
    fs.unlinkSync(entry.path)
  })

  console.log('[reset] Backup complete.')
}

// --- Main ---
console.log('=== E2E Database Reset ===\n')

// Step 1: Run Django cleanup (dry-run or confirm)
const cleanup = runDjangoCleanup(isConfirmed)
console.log(cleanup.output)

if (cleanup.status !== 0) {
  console.error('[reset] Django cleanup failed.')
  process.exit(1)
}

if (!isConfirmed) {
  // Dry run already printed by Django command
  process.exit(0)
}

// Step 2: Sync sequences
console.log('[reset] Syncing sequences...')
const dbConfig = getDbConfig()
syncSequences(dbConfig)
console.log('[reset] Sequences synced.')

// Step 3: Take fresh clean backup
takeBackup(dbConfig)

console.log('\n=== Reset complete. Database is clean and ready for E2E tests. ===')
