import { spawnSync } from 'child_process'
import fs from 'fs'
import os from 'os'
import path from 'path'
import { ensureXeroConnected } from './xero-login'
import { getBackupsDir, getDbConfig } from './db-backup-utils'

const LOCK_FILE = path.join(os.tmpdir(), 'playwright-e2e.lock')

function formatTimestamp(date: Date): string {
  const pad = (value: number) => value.toString().padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(
    date.getHours(),
  )}${pad(date.getMinutes())}${pad(date.getSeconds())}`
}

export default async function globalSetup() {
  if (fs.existsSync(LOCK_FILE)) {
    const pid = fs.readFileSync(LOCK_FILE, 'utf8').trim()
    throw new Error(`E2E tests already running (PID: ${pid}). Kill it or delete ${LOCK_FILE}`)
  }
  fs.writeFileSync(LOCK_FILE, process.pid.toString())

  console.log('[db] Backing up database before tests...')
  const dbConfig = getDbConfig()
  const backupDir = getBackupsDir()
  fs.mkdirSync(backupDir, { recursive: true })

  const backupFile = path.join(backupDir, `backup_${formatTimestamp(new Date())}.sql`)
  const outputFd = fs.openSync(backupFile, 'w')

  // Check if mysqldump supports --column-statistics (MySQL 8.x only, not MariaDB)
  const versionCheck = spawnSync('mysqldump', ['--version'], { encoding: 'utf8' })
  const isMySQL8 =
    versionCheck.stdout?.includes('MySQL') && !versionCheck.stdout?.includes('MariaDB')

  const mysqldumpArgs = [
    '-h',
    dbConfig.host,
    '-P',
    dbConfig.port,
    '-u',
    dbConfig.user,
    `-p${dbConfig.password}`,
    ...(isMySQL8 ? ['--column-statistics=0'] : []),
    dbConfig.database,
  ]

  const result = spawnSync('mysqldump', mysqldumpArgs, { stdio: ['ignore', outputFd, 'inherit'] })

  fs.closeSync(outputFd)

  if (result.status !== 0) {
    throw new Error(`Database backup failed (exit code ${result.status}).`)
  }

  fs.writeFileSync(path.join(backupDir, '.latest_backup'), backupFile, 'utf8')

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

  console.log(`[db] Backup complete: ${backupFile}`)

  console.log('[xero] Ensuring Xero connection...')
  await ensureXeroConnected()
}
