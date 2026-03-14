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

export function getDbConfig(): DbConfig {
  const frontendDir = getFrontendDir()
  const backendEnvPath = resolveBackendEnvPath(frontendDir)
  const backendEnv = parseEnvFile(backendEnvPath)

  const database = backendEnv.MYSQL_DATABASE
  const user = backendEnv.MYSQL_DB_USER
  const password = backendEnv.DB_PASSWORD

  if (!database || !user || !password) {
    throw new Error(
      'Backend .env missing required MYSQL_DATABASE, MYSQL_DB_USER, or DB_PASSWORD entries.',
    )
  }

  return {
    host: backendEnv.DB_HOST || 'localhost',
    port: backendEnv.DB_PORT || '3306',
    database,
    user,
    password,
  }
}
