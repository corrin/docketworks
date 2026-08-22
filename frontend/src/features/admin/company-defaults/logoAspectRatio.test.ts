import { afterEach, describe, expect, it, vi } from 'vitest'

import { aspectRatioProblem } from './logoAspectRatio'

/** jsdom implements neither image decoding nor object URLs; a fake `Image`
 * resolves its load/error listeners synchronously enough for these to stay
 * unit tests, matching the production code's addEventListener usage. */
function stubImage(result: { width: number; height: number } | 'error'): void {
  class FakeImage {
    naturalWidth = 0
    naturalHeight = 0
    private loadListener: (() => void) | null = null
    private errorListener: (() => void) | null = null
    addEventListener(type: 'load' | 'error', listener: () => void): void {
      if (type === 'load') this.loadListener = listener
      else this.errorListener = listener
    }
    set src(_value: string) {
      queueMicrotask(() => {
        if (result === 'error') {
          this.errorListener?.()
          return
        }
        this.naturalWidth = result.width
        this.naturalHeight = result.height
        this.loadListener?.()
      })
    }
  }
  vi.stubGlobal('Image', FakeImage)
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:fake'),
    revokeObjectURL: vi.fn(),
  })
}

const file = () => new File([new Uint8Array([1, 2, 3])], 'logo.png', { type: 'image/png' })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('aspectRatioProblem', () => {
  it('passes an unregistered field key without reading the file', async () => {
    // No stubImage call: a dimension read here would throw, proving the
    // unregistered-key branch short-circuits before touching Image/URL.
    expect(await aspectRatioProblem('company_url', file())).toBeNull()
  })

  it('accepts a square logo within the 0.85-1.18 band', async () => {
    stubImage({ width: 100, height: 100 })
    expect(await aspectRatioProblem('logo', file())).toBeNull()
  })

  it('rejects a logo outside the square band with the v1 message shape', async () => {
    stubImage({ width: 200, height: 100 })
    const problem = await aspectRatioProblem('logo', file())
    expect(problem).toBe(
      'This image is 2.00:1 (width:height). Expected approximately 1:1 (square) for the ' +
        'square logo field. Please upload a square image.',
    )
  })

  it('accepts a wide letterhead logo within the 2.5-8.0 band', async () => {
    stubImage({ width: 400, height: 100 })
    expect(await aspectRatioProblem('logo_wide', file())).toBeNull()
  })

  it('rejects a logo_wide that is not wide enough', async () => {
    stubImage({ width: 100, height: 100 })
    const problem = await aspectRatioProblem('logo_wide', file())
    expect(problem).toBe(
      'This image is 1.00:1 (width:height). Expected between 2.5:1 and 8:1 (wide) for the ' +
        'wide letterhead logo field. Please upload a wide letterhead-style image (around 4× ' +
        'wider than tall).',
    )
  })

  it('reports invalid dimensions for a zero-height image', async () => {
    stubImage({ width: 100, height: 0 })
    expect(await aspectRatioProblem('logo', file())).toBe('Image has invalid dimensions.')
  })

  it('reports an unreadable file without logging it', async () => {
    stubImage('error')
    const errorSpy = vi.spyOn(console, 'error')
    expect(await aspectRatioProblem('logo', file())).toBe(
      'Could not read image file. Please try a different image.',
    )
    expect(errorSpy).not.toHaveBeenCalled()
  })
})
