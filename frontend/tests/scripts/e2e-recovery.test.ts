import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { acquireE2ELock } from './global-setup'
import { parseSavedXeroToken, requireBackupFile } from './global-teardown'

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

describe('Xero token custody', () => {
  /**
   * The saved row is parsed BEFORE the restore as well as after, so a token
   * that cannot be re-injected stops the teardown while the database still
   * holds a working one. Xero rotates refresh tokens and will not reissue
   * without a human completing consent, so "find out afterwards" means the
   * connection is already gone.
   */
  const validRow = {
    id: 'a3f1',
    token_type: 'Bearer',
    access_token: 'access',
    refresh_token: 'refresh',
    expires_at: '2026-08-16T00:00:00Z',
    scope: 'payroll.timesheets',
  }

  it('accepts a complete row, and a null scope', () => {
    expect(parseSavedXeroToken(JSON.stringify(validRow)).refresh_token).toBe('refresh')
    expect(parseSavedXeroToken(JSON.stringify({ ...validRow, scope: null })).scope).toBe(null)
  })

  it('refuses a row missing the refresh token', () => {
    const { refresh_token: _dropped, ...withoutRefresh } = validRow
    expect(() => parseSavedXeroToken(JSON.stringify(withoutRefresh))).toThrow(/refresh_token/)
  })

  it('refuses a non-object and a non-string scope', () => {
    expect(() => parseSavedXeroToken('null')).toThrow(/not an object/)
    expect(() => parseSavedXeroToken(JSON.stringify({ ...validRow, scope: 42 }))).toThrow(/scope/)
  })
})
