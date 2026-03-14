#!/usr/bin/env node

import 'dotenv/config'
import { execSync } from 'child_process'
import fs from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join, delimiter } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const projectRoot = join(__dirname, '..')
const backendPath = join(projectRoot, '..', 'jobs_manager')
const customVenvPath = process.env.JOBS_MANAGER_VENV_PATH?.trim()
const isWindows = process.platform === 'win32'

const DEFAULT_COMMAND = 'poetry run python manage.py spectacular --format openapi'

function resolveVenvBin(venvPath) {
  return isWindows ? join(venvPath, 'Scripts') : join(venvPath, 'bin')
}

function resolvePythonExecutable(venvPath) {
  const binDir = resolveVenvBin(venvPath)
  return isWindows ? join(binDir, 'python.exe') : join(binDir, 'python')
}

function getSchemaCommand() {
  if (!customVenvPath) {
    return DEFAULT_COMMAND
  }

  const pythonExecutable = resolvePythonExecutable(customVenvPath)
  return '"' + pythonExecutable + '" manage.py spectacular --format openapi'
}

function buildExecutionEnv() {
  if (!customVenvPath) {
    return process.env
  }

  const binDir = resolveVenvBin(customVenvPath)
  const existingPath = process.env.PATH ?? ''

  return {
    ...process.env,
    VIRTUAL_ENV: customVenvPath,
    PATH: binDir + delimiter + existingPath,
  }
}

function generateSchema() {
  console.log('Generating schema from ' + backendPath + '...')

  const schemaCommand = getSchemaCommand()
  const schema = execSync(schemaCommand, {
    cwd: backendPath,
    encoding: 'utf-8',
    timeout: 120000,
    env: buildExecutionEnv(),
  })

  const schemaPath = join(projectRoot, 'schema.yml')
  fs.writeFileSync(schemaPath, schema)
  console.log('Schema generated successfully')
}

try {
  generateSchema()
} catch (error) {
  const isCI = process.env.CI === 'true' || process.env.GITHUB_ACTIONS === 'true'

  if (isCI) {
    console.log('Could not generate schema (CI mode - using existing schema):', error.message)
    process.exit(0)
  } else {
    console.error('Failed to generate schema:', error.message)
    process.exit(1)
  }
}
