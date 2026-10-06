export type XeroMode = 'fake' | 'real'

/** Only an explicit E2E selection enables live calls; application .env is not intent. */
export function xeroMode(env: NodeJS.ProcessEnv = process.env): XeroMode {
  const value = env.E2E_XERO_MODE ?? 'fake'
  if (value !== 'fake' && value !== 'real') throw new Error(`Invalid E2E_XERO_MODE: ${value}`)
  return value
}

export function configureXeroMode(env: NodeJS.ProcessEnv = process.env): XeroMode {
  const mode = xeroMode(env)
  env.E2E_XERO_MODE = mode
  env.XERO_FAKE = mode === 'fake' ? 'true' : 'false'
  return mode
}

/** A recovery must never interpret missing run metadata as permission for live cleanup. */
export function recordedXeroMode(lockContents: string): XeroMode {
  const recorded = lockContents.split('\n')[3]?.trim()
  if (recorded !== 'fake' && recorded !== 'real')
    throw new Error('E2E lock has no valid Xero mode; refusing Xero cleanup.')
  if (recorded !== xeroMode())
    throw new Error('E2E lock Xero mode disagrees with this process; refusing Xero cleanup.')
  return recorded
}
