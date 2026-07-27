import { afterEach, beforeEach, describe, expect, it } from 'vitest'

// The forwarder lives under tests/ (Playwright fixtures) which vitest excludes
// as a test-file root, but its pure bridge functions are imported here so the
// area->app-namespace mapping the whole forwarder depends on is guarded by unit
// tests. Relative import because `@/` only maps into src/.
import { browserDebugGlob, enabledAreas } from '../../tests/fixtures/debug-forwarder'

describe('debug-forwarder bridge', () => {
  const originalDebug = process.env.DEBUG

  beforeEach(() => {
    delete process.env.DEBUG
  })

  afterEach(() => {
    if (originalDebug === undefined) {
      delete process.env.DEBUG
    } else {
      process.env.DEBUG = originalDebug
    }
  })

  it('enables nothing when DEBUG is unset', () => {
    expect(enabledAreas()).toEqual([])
    expect(browserDebugGlob()).toBeNull()
  })

  it('ignores non-e2e debug namespaces', () => {
    process.env.DEBUG = 'job:autosave'
    expect(enabledAreas()).toEqual([])
    expect(browserDebugGlob()).toBeNull()
  })

  it('maps a single area to its app glob', () => {
    process.env.DEBUG = 'e2e:autosave'
    expect(enabledAreas()).toEqual(['e2e:autosave'])
    expect(browserDebugGlob()).toBe('job:autosave')
  })

  it('joins multiple areas into a comma-separated glob', () => {
    process.env.DEBUG = 'e2e:kanban,e2e:job'
    expect(browserDebugGlob()).toBe('kanban:*,job:*')
  })

  it('drops an e2e area that has no bridge entry', () => {
    process.env.DEBUG = 'e2e:autosave,e2e:unknown'
    expect(enabledAreas()).toEqual(['e2e:autosave', 'e2e:unknown'])
    expect(browserDebugGlob()).toBe('job:autosave')
  })
})
