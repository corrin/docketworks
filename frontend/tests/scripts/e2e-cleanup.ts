/**
 * Run the backend's E2E cleanup, which removes this run's writes from Xero.
 *
 * One spawn for the two callers that need it: the pre-run reset, which clears
 * whatever a previous crashed run left, and global teardown, which undoes the
 * run that has just finished. Both reach the same management command, and a
 * second copy of the venv path would be a second thing to keep true.
 *
 * The command reads the Xero ids off the local rows, so teardown must call it
 * BEFORE the database restore: the restore erases the only record of what the
 * run created in the organisation.
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { assertSpawnSucceeded } from './process-result'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const backendDir = path.resolve(scriptDir, '..', '..', '..')

/** Run `manage.py e2e_cleanup`; a dry run unless `confirmed`. Throws on failure. */
export function runE2ECleanup(confirmed: boolean): void {
  const python = path.join(backendDir, '.venv', 'bin', 'python')
  const args = [path.join(backendDir, 'manage.py'), 'e2e_cleanup']
  if (confirmed) args.push('--confirm')
  const result = spawnSync(python, args, { cwd: backendDir, stdio: 'inherit' })
  assertSpawnSucceeded('e2e_cleanup', result)
}
