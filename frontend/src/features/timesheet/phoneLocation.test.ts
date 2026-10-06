import { afterEach, describe, expect, it, vi } from 'vitest'

import { phoneLocation } from './useWorkshopDay'

const AT_THE_WORKSHOP = { latitude: -36.85, longitude: 174.76 }

/** A position service that answers every read with the one fix. */
function geolocationAt(at: { latitude: number; longitude: number }) {
  const coords: GeolocationCoordinates = {
    ...at,
    accuracy: 10,
    altitude: null,
    altitudeAccuracy: null,
    heading: null,
    speed: null,
    toJSON: () => at,
  }
  const position: GeolocationPosition = { coords, timestamp: Date.now(), toJSON: () => at }
  return {
    getCurrentPosition: (found: PositionCallback) => found(position),
    watchPosition: () => 0,
    clearWatch: () => undefined,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('phoneLocation', () => {
  // The rule: no location means the write goes ahead, marked; never a failed write.
  it('reads the position where the phone has no Permissions API', async () => {
    vi.stubGlobal('navigator', { geolocation: geolocationAt(AT_THE_WORKSHOP) })

    await expect(phoneLocation()).resolves.toEqual(AT_THE_WORKSHOP)
  })

  it('reads the position where the permission query is refused', async () => {
    vi.stubGlobal('navigator', {
      geolocation: geolocationAt(AT_THE_WORKSHOP),
      permissions: { query: () => Promise.reject(new TypeError('geolocation is not a name')) },
    })

    await expect(phoneLocation()).resolves.toEqual(AT_THE_WORKSHOP)
  })

  it('answers no location where the phone has no position service', async () => {
    vi.stubGlobal('navigator', {})

    await expect(phoneLocation()).resolves.toBeNull()
  })
})
