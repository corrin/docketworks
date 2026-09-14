/**
 * Run the backend's E2E cleanup, which removes this run's writes from Xero.
 *
 * One call for the two callers that need it: the pre-run reset, which clears
 * whatever a previous crashed run left, and global teardown, which undoes the
 * run that has just finished.
 *
 * The command reads the Xero ids off the local rows, so teardown must call it
 * BEFORE the database restore: the restore erases the only record of what the
 * run created in the organisation.
 */
import { runManagePy } from './db-backup-utils'

/** Run `manage.py e2e_cleanup`; a dry run unless `confirmed`. Throws on failure. */
export function runE2ECleanup(confirmed: boolean): void {
  const args = ['e2e_cleanup']
  if (confirmed) args.push('--confirm')
  process.stdout.write(runManagePy(args))
}
