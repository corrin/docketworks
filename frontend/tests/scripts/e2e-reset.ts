/** Reset the development database to a state safe for Playwright. */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  formatTimestamp,
  getBackupsDir,
  getDbConfig,
  runPgDump,
  syncSequences,
} from './db-backup-utils'
import { assertSpawnSucceeded } from './process-result'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const backendDir = path.resolve(scriptDir, '..', '..', '..')
const lockFile = path.join(os.tmpdir(), 'playwright-e2e.lock')
const confirmed = process.argv.includes('--confirm')

type LockState = 'none' | 'stale' | 'live'

function inspectLock(): LockState {
  if (!fs.existsSync(lockFile)) return 'none'
  const pid = Number.parseInt(fs.readFileSync(lockFile, 'utf8').split('\n')[0] ?? '', 10)
  if (!Number.isInteger(pid)) throw new Error(`Invalid E2E lock file: ${lockFile}`)
  try {
    process.kill(pid, 0)
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ESRCH') return 'stale'
    throw error
  }
  return 'live'
}

/**
 * The pg_dump that global-setup preserved for the crashed run (line 2 of the
 * lock). Once the reset has cleaned the database and taken its own backup,
 * that dump is superseded and keeping it would only accumulate orphans.
 * The lock is world-writable local state, not a trusted manifest, so the
 * path must resolve to a generated backup inside the backups directory
 * before anything deletes it.
 */
function supersededCrashBackup(): string | undefined {
  const backupPath = fs.readFileSync(lockFile, 'utf8').split('\n')[1]?.trim()
  if (!backupPath) return undefined
  const resolved = path.resolve(backupPath)
  const isGeneratedBackup =
    path.dirname(resolved) === path.resolve(getBackupsDir()) &&
    /^backup_.+\.sql$/.test(path.basename(resolved))
  if (!isGeneratedBackup) {
    console.log(`[reset] Lock references a non-backup path; leaving it untouched: ${backupPath}`)
    return undefined
  }
  if (!fs.existsSync(resolved)) return undefined
  return resolved
}

function runCleanup(): void {
  const python = path.join(backendDir, '.venv', 'bin', 'python')
  const args = [path.join(backendDir, 'manage.py'), 'e2e_cleanup']
  if (confirmed) args.push('--confirm')
  const result = spawnSync(python, args, { cwd: backendDir, stdio: 'inherit' })
  assertSpawnSucceeded('e2e_cleanup', result)
}

function takeCleanBackup(): void {
  const config = getDbConfig()
  const backupDir = getBackupsDir()
  fs.mkdirSync(backupDir, { recursive: true })
  const backupFile = path.join(backupDir, `reset_backup_${formatTimestamp(new Date())}.sql`)
  runPgDump(config, backupFile)
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

const lockState = inspectLock()
if (lockState === 'live' && confirmed) {
  throw new Error(
    `E2E tests already running (lock: ${lockFile}). Refusing to reset their database.`,
  )
}
console.log('=== E2E Database Reset ===')
if (lockState === 'live') {
  // A dry run mutates nothing, so it may report even while a suite runs —
  // that is precisely when an operator wants to look.
  console.log('[reset] A live E2E run holds the lock; reporting only.')
}
runCleanup()
if (confirmed) {
  syncSequences()
  takeCleanBackup()
  if (lockState === 'stale') {
    const crashBackup = supersededCrashBackup()
    if (crashBackup) {
      fs.rmSync(crashBackup)
      console.log(`[reset] Removed superseded crash backup: ${crashBackup}`)
    }
    fs.rmSync(lockFile)
    console.log(`[reset] Removed stale lock: ${lockFile}`)
  }
  console.log('=== Reset complete. Database is clean and ready for E2E. ===')
} else {
  console.log('=== Dry run only. Re-run with --confirm to delete and re-baseline. ===')
}
