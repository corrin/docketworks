/** Local credential custody for a managed fake run, including failed startup. */
import fs from 'node:fs'
import { pathToFileURL } from 'node:url'
import { getDbConfig } from './db-backup-utils'
import { reinjectXeroToken, saveActiveXeroToken } from './global-teardown'
import { xeroMode } from './xero-mode'

export function tokenCustody(action: string, file: string): void {
  if (xeroMode() !== 'fake') throw new Error('Original-token custody is only for fake Xero runs.')
  const config = getDbConfig()
  if (action === 'save') {
    saveActiveXeroToken(config, file)
  } else if (action === 'restore') {
    reinjectXeroToken(config, fs.readFileSync(file, 'utf8'))
  } else {
    throw new Error(`Unknown token custody action: ${action}`)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [action, file] = process.argv.slice(2)
  if (!action || !file) throw new Error('Usage: xero-token-custody.ts save|restore <private-file>')
  tokenCustody(action, file)
}
