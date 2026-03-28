# Fix: Remove contenttypes from backup

## Context

Production data restore fails because the backup includes Django `contenttypes` records. When `migrate` runs on a fresh database, Django auto-creates content types (via `post_migrate` signal). Then `loaddata` tries to insert production's content types and hits a unique constraint violation on `(app_label, model)`.

Content types are fully deterministic — same code produces the same content types. No backed-up model references `content_type_id`. They carry zero business data and should not be in the fixture.

## Changes

### 1. Remove contenttypes from backup command
**File:** `apps/workflow/management/commands/backport_data_backup.py` (line 103)

Remove:
```python
"contenttypes",  # Django internal - needed for migrations
```

### 2. Update restore docs
**File:** `docs/backup-restore-process.md`

No doc changes needed — the restore steps don't mention contenttypes. The fix is invisible to the restore process.

## Verification

1. Remove the line from the backup command
2. Re-run the restore from Step 5 (reset database) through Step 8 (loaddata)
3. Confirm `loaddata` completes without errors
