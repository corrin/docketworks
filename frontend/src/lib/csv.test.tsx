import { describe, expect, it, vi } from 'vitest'

import { downloadCsv } from './csv'

// A .tsx sibling to csv.test.ts because this project splits suites by
// extension: .test.ts runs under node, .test.tsx under jsdom. The download
// half needs a DOM; the serialisation half deliberately does not.

describe('downloadCsv', () => {
  it('names the file, hands it to the browser, and releases the URL after the download', () => {
    // jsdom implements neither half of the object-URL API, so the test
    // supplies both and asserts the pairing.
    vi.useFakeTimers()
    const revoked: string[] = []
    const created: Blob[] = []
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn((blob: Blob) => {
        created.push(blob)
        return 'blob:stub'
      }),
      revokeObjectURL: vi.fn((url: string) => revoked.push(url)),
    })
    const clicks: string[] = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this.download)
    })

    downloadCsv('sales-forecast-report-2026-08-21.csv', ['Month'], [['Jun 2026']])

    expect(clicks).toEqual(['sales-forecast-report-2026-08-21.csv'])
    expect(created).toHaveLength(1)
    // Opus: the release is deferred, not immediate. Revoking on the next
    // statement races the browser reading the blob — Chromium wins that race
    // and Safari does not, and a chromium-only E2E run would never show it.
    expect(revoked).toEqual([])
    vi.runAllTimers()
    expect(revoked).toEqual(['blob:stub'])
    // The anchor is removed again: an export-per-click page would otherwise
    // accumulate one dead node per export.
    expect(document.querySelectorAll('a')).toHaveLength(0)

    click.mockRestore()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })
})
