import { afterEach, expect, it, vi } from 'vitest'
vi.mock('child_process', () => ({ spawnSync: vi.fn() }))
import { spawnSync } from 'child_process'
import { runManagePy } from './db-backup-utils'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetAllMocks()
})

it.each([
  [undefined, 'false', 'true'],
  ['fake', 'false', 'true'],
  ['real', 'true', 'false'],
])(
  'passes selected mode %s to cleanup commands despite inherited XERO_FAKE=%s',
  (mode, inherited, expected) => {
    vi.stubEnv('E2E_XERO_MODE', mode)
    vi.stubEnv('XERO_FAKE', inherited)
    vi.mocked(spawnSync).mockReturnValue({
      pid: 1,
      status: 0,
      signal: null,
      output: [],
      stdout: '',
      stderr: '',
    })
    runManagePy(['e2e_cleanup', '--confirm'])
    expect(spawnSync).toHaveBeenCalledWith(
      expect.any(String),
      ['manage.py', 'e2e_cleanup', '--confirm'],
      expect.objectContaining({ env: expect.objectContaining({ XERO_FAKE: expected }) }),
    )
  },
)

it('does not start a cleanup subprocess with an invalid mode', () => {
  vi.stubEnv('E2E_XERO_MODE', 'typo')
  expect(() => runManagePy(['e2e_cleanup', '--confirm'])).toThrow('Invalid E2E_XERO_MODE')
  expect(spawnSync).not.toHaveBeenCalled()
})
