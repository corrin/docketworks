import { describe, expect, it } from 'vitest'

import { assertSpawnSucceeded } from './process-result'

describe('assertSpawnSucceeded', () => {
  it('accepts a successful process', () => {
    expect(() =>
      assertSpawnSucceeded('command', { error: undefined, signal: null, status: 0, stderr: '' }),
    ).not.toThrow()
  })

  it('reports an executable startup failure', () => {
    expect(() =>
      assertSpawnSucceeded('sequence sync', {
        error: new Error('spawn /missing/python ENOENT'),
        signal: null,
        status: null,
        stderr: '',
      }),
    ).toThrow('sequence sync failed (could not start: spawn /missing/python ENOENT)')
  })

  it('reports exit, signal, and stderr details', () => {
    expect(() =>
      assertSpawnSucceeded('restore', {
        error: undefined,
        signal: 'SIGTERM',
        status: 1,
        stderr: Buffer.from('database unavailable'),
      }),
    ).toThrow('exit code 1; signal SIGTERM; stderr: database unavailable')
  })
})
