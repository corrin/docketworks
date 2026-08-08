/** Reset the development database to a state safe for Playwright. */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { getBackupsDir, getDbConfig, syncSequences } from './db-backup-utils'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const backendDir = path.resolve(scriptDir, '..', '..', '..')
const lockFile = path.join(os.tmpdir(), 'playwright-e2e.lock')
const confirmed = process.argv.includes('--confirm')

function staleLock(): boolean {
  if (!fs.existsSync(lockFile)) return false
  const pid = Number.parseInt(fs.readFileSync(lockFile, 'utf8').split('\n')[0] ?? '', 10)
  if (!Number.isInteger(pid)) throw new Error(`Invalid E2E lock file: ${lockFile}`)
  try {
    process.kill(pid, 0)
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ESRCH') return true
    throw error
  }
  throw new Error(`E2E tests already running (PID: ${pid}). Refusing to reset their database.`)
}

function runCleanup(): void {
  const python = path.join(backendDir, '.venv', 'bin', 'python')
  const args = [path.join(backendDir, 'manage.py'), 'e2e_cleanup']
  if (confirmed) args.push('--confirm')
  const result = spawnSync(python, args, { cwd: backendDir, stdio: 'inherit' })
  if (result.status !== 0) throw new Error(`e2e_cleanup failed (exit code ${result.status}).`)
}

function takeCleanBackup(): void {
  const config = getDbConfig()
  const backupDir = getBackupsDir()
  fs.mkdirSync(backupDir, { recursive: true })
  const stamp = new Date()
    .toISOString()
    .replace(/[-:TZ.]/g, '')
    .slice(0, 14)
  const backupFile = path.join(backupDir, `reset_backup_${stamp}.sql`)
  const output = fs.openSync(backupFile, 'w')
  const args = ['--clean', '--if-exists', '-h', config.host]
  if (config.port) args.push('-p', config.port)
  args.push('-U', config.user, config.database)
  const result = spawnSync('pg_dump', args, {
    stdio: ['ignore', output, 'inherit'],
    env: { ...process.env, PGPASSWORD: config.password },
  })
  fs.closeSync(output)
  if (result.status !== 0) {
    fs.rmSync(backupFile, { force: true })
    throw new Error(`Database backup failed (exit code ${result.status}).`)
  }
  fs.writeFileSync(path.join(backupDir, '.latest_backup'), backupFile, 'utf8')
  const backups = fs
    .readdirSync(backupDir)
    .filter((name) => name.startsWith('reset_backup_') && name.endsWith('.sql'))
    .map((name) => ({
      path: path.join(backupDir, name),
      mtime: fs.statSync(path.join(backupDir, name)).mtimeMs,
    }))
    .toSorted((left, right) => right.mtime - left.mtime)
  for (const backup of backups.slice(5)) fs.rmSync(backup.path)
  console.log(`[reset] Clean backup: ${backupFile}`)
}

const hadStaleLock = staleLock()
console.log('=== E2E Database Reset ===')
runCleanup()
if (confirmed) {
  syncSequences()
  takeCleanBackup()
  if (hadStaleLock) {
    fs.rmSync(lockFile)
    console.log(`[reset] Removed stale lock: ${lockFile}`)
  }
  console.log('=== Reset complete. Database is clean and ready for E2E. ===')
}
