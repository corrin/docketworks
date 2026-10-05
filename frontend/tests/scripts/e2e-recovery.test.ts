import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { acquireE2ELock } from './global-setup'
import {
  afterCeleryStops,
  managedCelery,
  parseSavedXeroToken,
  requireBackupFile,
  type ProcessControl,
} from './global-teardown'

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

/** Processes that exit a given number of polls after being asked to, or never. */
function control(exitsAfterPolls: number | null): ProcessControl & { events: string[] } {
  const events: string[] = []
  const asked = new Set<number>()
  let polls = 0
  return {
    events,
    terminate: (sessionId) => {
      asked.add(sessionId)
      events.push(`terminate ${sessionId}`)
    },
    running: (sessionId) =>
      !(asked.has(sessionId) && exitsAfterPolls !== null && polls >= exitsAfterPolls),
    sleep: () => {
      polls += 1
    },
  }
}

describe("the database is rewritten only once the run's Celery has stopped", () => {
  const managed = [
    { name: 'Celery worker', sessionId: 11 },
    { name: 'Celery beat', sessionId: 12 },
  ]

  it('stops the worker and beat, waits for them, then rewrites', () => {
    const processes = control(3)
    afterCeleryStops(managed, () => processes.events.push('rewrite'), processes, 10_000)

    expect(processes.events).toEqual(['terminate 11', 'terminate 12', 'rewrite'])
  })

  it('never rewrites under a worker that will not stop, and says which', () => {
    const processes = control(null)
    const rewrite = () => processes.events.push('rewrite')

    expect(() => afterCeleryStops(managed, rewrite, processes, 2_000)).toThrow(
      'Celery worker and Celery beat still running 2s after being asked to stop',
    )
    expect(processes.events).not.toContain('rewrite')
  })

  it('leaves a stack this run did not start alone', () => {
    const processes = control(null)
    afterCeleryStops(null, () => processes.events.push('rewrite'), processes)

    expect(processes.events).toEqual(['rewrite'])
  })

  it("reads the launcher's two process ids, and none from a bare run", () => {
    expect(managedCelery({})).toBeNull()
    expect(managedCelery({ E2E_CELERY_WORKER_PID: '11', E2E_CELERY_BEAT_PID: '12' })).toEqual(
      managed,
    )
    expect(() => managedCelery({ E2E_CELERY_WORKER_PID: '11' })).toThrow('but not the other')
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
