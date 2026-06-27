import { describe, expect, it } from 'vitest'
import { parseArgs } from '@/utils/captureScreenshots'

describe('capture-screenshots CLI parsing', () => {
  it('keeps manual screenshot mode when no URL is supplied', () => {
    expect(parseArgs([])).toEqual({ fullPage: false })
  })

  it('parses single-page screenshot options', () => {
    expect(
      parseArgs([
        '--url',
        '/process-documents/forms/incident/example',
        '--output',
        '/tmp/example.png',
        '--wait-for',
        'main',
        '--full-page',
      ]),
    ).toEqual({
      url: '/process-documents/forms/incident/example',
      output: '/tmp/example.png',
      waitFor: 'main',
      fullPage: true,
    })
  })

  it('rejects missing flag values', () => {
    expect(() => parseArgs(['--url'])).toThrow('--url requires a non-empty value')
    expect(() => parseArgs(['--output', '--full-page'])).toThrow(
      '--output requires a non-empty value',
    )
  })

  it('rejects unknown arguments', () => {
    expect(() => parseArgs(['--cookies-stdin'])).toThrow('Unknown argument: --cookies-stdin')
  })
})
