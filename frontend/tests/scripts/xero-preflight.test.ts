import { describe, expect, it } from 'vitest'

import { harnessExpectsFake, xeroPreflightIssues, type XeroStatus } from './global-setup'

const connected: XeroStatus = {
  connected: true,
  xeroReadonly: false,
  productionClient: false,
  xeroFake: false,
}

describe('xeroPreflightIssues under the fake Xero (ADR 0060)', () => {
  it('passes a real backend for a real run and a fake backend for a fake run', () => {
    expect(xeroPreflightIssues(connected, false)).toEqual([])
    expect(xeroPreflightIssues({ ...connected, xeroFake: true }, true)).toEqual([])
  })

  it('refuses a run whose flag disagrees with the backend, either way round', () => {
    const [notAsked] = xeroPreflightIssues({ ...connected, xeroFake: true }, false)
    expect(notAsked).toContain('not started with --use-fake-xero')
    const [askedButReal] = xeroPreflightIssues(connected, true)
    expect(askedButReal).toContain('answering from real Xero')
  })

  it('fails closed when the backend does not say whether it is the fake', () => {
    const [issue] = xeroPreflightIssues({ ...connected, xeroFake: null }, false)
    expect(issue).toContain('xero_fake')
  })

  it('reads the mode run_e2e.sh exports, and nothing else counts as fake', () => {
    expect(harnessExpectsFake({ XERO_FAKE: 'true' })).toBe(true)
    expect(harnessExpectsFake({ XERO_FAKE: 'false' })).toBe(false)
    expect(harnessExpectsFake({})).toBe(false)
  })
})
