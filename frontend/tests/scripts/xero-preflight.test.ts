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
    expect(notAsked).toContain('mode disagrees')
    const [askedButReal] = xeroPreflightIssues(connected, true)
    expect(askedButReal).toContain('mode disagrees')
  })

  it('fails closed when the backend does not say whether it is the fake', () => {
    const [issue] = xeroPreflightIssues({ ...connected, xeroFake: null }, false)
    expect(issue).toContain('xero_fake')
  })

  it('lets the fake answer for a production app, and refuses a real production app', () => {
    const production = { ...connected, productionClient: true }
    expect(xeroPreflightIssues({ ...production, xeroFake: true }, true)).toEqual([])
    const [issue] = xeroPreflightIssues(production, false)
    expect(issue).toContain('production Xero app with writes enabled')
    expect(issue).not.toContain('XERO_READONLY')
  })

  it('defaults to fake and requires an explicit live harness selection', () => {
    expect(harnessExpectsFake({ XERO_FAKE: 'true' })).toBe(true)
    expect(harnessExpectsFake({ XERO_FAKE: 'false' })).toBe(true)
    expect(harnessExpectsFake({})).toBe(true)
    expect(harnessExpectsFake({ E2E_XERO_MODE: 'real', XERO_FAKE: 'true' })).toBe(false)
  })
})
