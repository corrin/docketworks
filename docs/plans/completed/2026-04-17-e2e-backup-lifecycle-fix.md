# E2E Backup Lifecycle Fix

## Context

The current setup/teardown uses a persistent `.latest_backup` file to track the backup path across runs. This causes two problems:

1. If setup fails (e.g. pre-flight check fails), teardown would restore a backup from a *previous* run — corrupting the DB. The current workaround deletes `.latest_backup` at setup start, which is indirect and confusing.
2. After teardown restores the backup, the file is never deleted. Backups accumulate and must be pruned (currently kept to 5). Once restored, the backup has no remaining purpose.

The fix: make the backup path per-run state (stored in the lock file), and delete the backup after successful restore.

## Approach

**Lock file carries the backup path.** The lock file already exists exactly for the duration of one run. When the backup succeeds, append the backup path as a second line:

```
<PID>
/absolute/path/to/backup.sql
```

Teardown reads the backup path from line 2 of the lock file. If no second line exists (setup aborted before backup), teardown skips restore. No `.latest_backup` file is needed at all.

**Backup deleted after successful restore.** Once teardown restores successfully, the backup file is deleted. If restore fails, the file is left in place for debugging. The "prune to 5" logic in setup is removed entirely.

## Changes

### `frontend/tests/scripts/global-setup.ts`

- Remove the block that deletes `.latest_backup` at startup (lines 74–79)
- After `pg_dump` succeeds, append the backup path as a second line to the lock file instead of writing `.latest_backup`
- Remove the "prune old backups" block (lines 140–151)

### `frontend/tests/scripts/global-teardown.ts`

In `restoreDatabase()`:
- Read the lock file instead of `.latest_backup` — extract the backup path from line 2
- If no second line, log and skip restore (setup never completed a backup)
- After successful restore, delete the backup file
- Remove all references to `getBackupsDir()` and `.latest_backup`

## Verification

Run the E2E tests normally and confirm:
- Setup completes, backup file is created, lock file contains two lines
- After teardown, backup file is gone, lock file is gone, DB is restored
- If pre-flight checks fail (e.g. temporarily break Xero check), confirm teardown does not restore anything
