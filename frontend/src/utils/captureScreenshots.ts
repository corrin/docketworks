export interface CliOptions {
  url?: string
  output?: string
  waitFor?: string
  fullPage: boolean
}

export function readFlagValue(argv: string[], index: number, flag: string): string {
  const value = argv[index + 1]
  if (!value || value.startsWith('--')) {
    throw new Error(`${flag} requires a non-empty value`)
  }
  return value
}

export function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = { fullPage: false }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]

    if (arg === '--url') {
      options.url = readFlagValue(argv, index, '--url')
      index += 1
    } else if (arg === '--output') {
      options.output = readFlagValue(argv, index, '--output')
      index += 1
    } else if (arg === '--wait-for') {
      options.waitFor = readFlagValue(argv, index, '--wait-for')
      index += 1
    } else if (arg === '--full-page') {
      options.fullPage = true
    } else {
      throw new Error(`Unknown argument: ${arg}`)
    }
  }

  return options
}
