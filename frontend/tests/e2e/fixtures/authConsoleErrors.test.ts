import { describe, expect, it } from 'vitest'
import { createRecoveredLoadAllowance } from './authConsoleErrors'

const chunk = 'https://app.example/assets/shell-abc.js'
const failed = {
  kind: 'console' as const,
  text: 'Failed to load resource: net::ERR_FAILED',
  capturedAt: 1000,
  url: chunk,
}

describe('createRecoveredLoadAllowance', () => {
  it('allows a network failure once the same URL loads afterwards', () => {
    const allowance = createRecoveredLoadAllowance()
    allowance.recordResponse({ url: chunk, status: 200, observedAt: 1500 })
    expect(allowance.isRecovered(failed)).toBe(true)
  })

  it('keeps a failure whose URL never loads', () => {
    const allowance = createRecoveredLoadAllowance()
    allowance.recordResponse({
      url: 'https://app.example/assets/other.js',
      status: 200,
      observedAt: 1500,
    })
    expect(allowance.isRecovered(failed)).toBe(false)
  })

  it('does not count a load that happened before the failure', () => {
    const allowance = createRecoveredLoadAllowance()
    allowance.recordResponse({ url: chunk, status: 200, observedAt: 900 })
    expect(allowance.isRecovered(failed)).toBe(false)
  })

  it('never allows an app console error or a server error status', () => {
    const allowance = createRecoveredLoadAllowance()
    allowance.recordResponse({ url: chunk, status: 500, observedAt: 1500 })
    expect(allowance.isRecovered(failed)).toBe(false)
    expect(
      allowance.isRecovered({
        kind: 'console',
        text: 'Uncaught TypeError',
        capturedAt: 1000,
        url: chunk,
      }),
    ).toBe(false)
  })
})
