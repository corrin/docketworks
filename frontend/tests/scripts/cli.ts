/**
 * Shared flag parsing for the analysis scripts in this directory.
 *
 * Built on node:util parseArgs rather than hand-rolled loops: the two
 * hand-rolled dialects (space-separated in analyze-e2e-trends,
 * equals-separated in analyze-e2e-rolling) each accepted only their own
 * syntax, and the rolling one silently ignored unknown flags — a typo like
 * --widnow=5 ran with the default. parseArgs accepts both syntaxes and
 * strict mode makes unknown flags throw.
 */
import { parseArgs } from 'node:util'

export interface CliArgs {
  positionals: string[]
  stringFlag(name: string): string | undefined
  integerFlag(name: string, fallback: number): number
  booleanFlag(name: string): boolean
}

export function parseCliArgs(config: {
  /** parseArgs option names: no leading dashes. */
  options: Record<string, { type: 'string' | 'boolean' }>
  allowPositionals?: boolean
  /** When set, a --help flag is added that prints this text and exits 0. */
  usage?: string
}): CliArgs {
  const options: Record<string, { type: 'string' | 'boolean' }> = { ...config.options }
  if (config.usage !== undefined) {
    options.help = { type: 'boolean' }
  }

  const { values, positionals } = parseArgs({
    options,
    strict: true,
    allowPositionals: config.allowPositionals ?? false,
  })

  if (config.usage !== undefined && values.help === true) {
    console.log(config.usage)
    process.exit(0)
  }

  const stringFlag = (name: string): string | undefined => {
    const value = values[name]
    if (value === undefined) return undefined
    if (typeof value !== 'string') {
      throw new Error(`--${name} is declared as a boolean flag, not a string option`)
    }
    return value
  }

  return {
    positionals,
    stringFlag,
    integerFlag: (name: string, fallback: number): number => {
      const raw = stringFlag(name)
      if (raw === undefined) return fallback
      const value = Number.parseInt(raw, 10)
      if (!Number.isFinite(value)) {
        throw new Error(`--${name} expects an integer, got: ${raw}`)
      }
      return value
    },
    booleanFlag: (name: string): boolean => values[name] === true,
  }
}
