import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

vi.mock('./db-backup-utils', () => ({
  getDbConfig: vi.fn(() => ({})),
  getBackupsDir: vi.fn(),
  runPsql: vi.fn(),
}))
import { getBackupsDir, runPsql } from './db-backup-utils'
import { beginFakeTokenSnapshot, finishFakeTokenSnapshot, restoreDatabase } from './global-teardown'

const token = JSON.stringify({
  id: 'test-id',
  token_type: 'Bearer',
  access_token: 'original',
  refresh_token: 'original-refresh',
  expires_at: '2026-10-04',
  scope: null,
})
let directory: string
beforeEach(() => {
  directory = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-custody-test-'))
  vi.mocked(getBackupsDir).mockReturnValue(directory)
  vi.mocked(runPsql).mockReturnValue(token)
  vi.stubEnv('E2E_XERO_MODE', 'fake')
  vi.stubEnv('E2E_XERO_TOKEN_SNAPSHOT', '')
})
afterEach(() => {
  fs.rmSync(directory, { recursive: true, force: true })
  vi.unstubAllEnvs()
  vi.resetAllMocks()
})

it('keeps a private original token across fake refreshes and removes it only after restoration', () => {
  const file = beginFakeTokenSnapshot()
  expect(file).not.toBeNull()
  if (file === null) throw new Error('Expected fake snapshot')
  expect(fs.statSync(file).mode & 0o777).toBe(0o600)
  expect(fs.statSync(path.dirname(file)).mode & 0o777).toBe(0o700)
  vi.mocked(runPsql).mockReturnValue('test-id')
  finishFakeTokenSnapshot(file)
  expect(vi.mocked(runPsql).mock.calls[1]?.[1]).toContain("access_token = 'original'")
  expect(fs.existsSync(file)).toBe(false)
})

it('retains the original credential file if reinjection fails', () => {
  const file = beginFakeTokenSnapshot()
  if (file === null) throw new Error('Expected fake snapshot')
  vi.mocked(runPsql).mockReturnValue('')
  expect(() => finishFakeTokenSnapshot(file)).toThrow('matched no row')
  expect(fs.readFileSync(file, 'utf8')).toBe(token)
})

it('leaves managed custody to the launcher so it restores after its writers stop', () => {
  const file = path.join(directory, 'managed.json')
  fs.writeFileSync(file, token)
  vi.stubEnv('E2E_XERO_TOKEN_SNAPSHOT', file)
  expect(beginFakeTokenSnapshot()).toBe(file)
  finishFakeTokenSnapshot(file)
  expect(runPsql).not.toHaveBeenCalled()
  expect(fs.existsSync(file)).toBe(true)
})

it.each(['1\nbackup\nrun', '1\nbackup\nrun\nreal'])(
  'refuses teardown before any database or vendor cleanup when mode metadata is unsafe: %s',
  (lock) => {
    expect(() => restoreDatabase(lock)).toThrow(/Xero mode/)
    expect(runPsql).not.toHaveBeenCalled()
  },
)
