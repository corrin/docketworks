#!/usr/bin/env node
/**
 * Ported from v1's check-api-contract-boundary.js, tightened: the generated API
 * layer may only be imported from src/api/. Features consume the re-exported
 * queryOptions/mutations from src/api/, never the generated internals — so data
 * access cannot fork into parallel implementations.
 *
 * v2 has NO allowlist. Do not add one.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = new URL('../src', import.meta.url).pathname
const violations = []

function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) {
      walk(path)
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      check(path)
    }
  }
}

function check(path) {
  const rel = relative(SRC, path)
  const insideApi = rel.startsWith('api/')
  const content = readFileSync(path, 'utf8')

  if (!insideApi && /from\s+['"](@\/api\/generated|\.\.?\/.*api\/generated)/.test(content)) {
    violations.push(`${rel}: imports api/generated internals (use @/api re-exports)`)
  }
  if (!insideApi && rel !== 'routeTree.gen.ts' && /from\s+['"]axios['"]/.test(content)) {
    violations.push(`${rel}: imports axios directly (transport lives in src/api only)`)
  }
}

walk(SRC)

if (violations.length > 0) {
  console.error('API boundary violations:')
  for (const v of violations) console.error(`  ${v}`)
  process.exit(1)
}
console.log('API boundary check passed.')
