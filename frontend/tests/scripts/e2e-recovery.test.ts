import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { acquireE2ELock } from './global-setup'
import { requireBackupFile } from './global-teardown'

const tempDirectories: string[] = []

afterEach(() => {
  for (const directory of tempDirectories.splice(0)) fs.rmSync(directory, { recursive: true })
})

describe('E2E recovery invariants', () => {
  it('acquires the lock atomically and preserves its original owner', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-lock-test-'))
    tempDirectories.push(directory)
    const lockFile = path.join(directory, 'playwright.lock')

    acquireE2ELock(lockFile, 101)

    expect(() => acquireE2ELock(lockFile, 202)).toThrow('E2E tests already running (PID: 101)')
    expect(fs.readFileSync(lockFile, 'utf8')).toBe('101')
  })

  it('rejects a lock with no completed backup path', () => {
    expect(() => requireBackupFile('101', () => true)).toThrow('Setup did not record a backup path')
  })

  it('rejects a missing backup and returns an existing one', () => {
    expect(() => requireBackupFile('101\n/missing.sql\nrun', () => false)).toThrow(
      'Backup file not found: /missing.sql',
    )
    expect(requireBackupFile('101\n/present.sql\nrun', () => true)).toBe('/present.sql')
  })
})
