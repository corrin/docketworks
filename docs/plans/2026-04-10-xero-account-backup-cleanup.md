# Plan: Include XeroAccount in backup, delete `backport_data_restore`

## Context

Restoring a production backup fails at Step 5 (`loaddata`) because the backup excludes `workflow.XeroAccount` but includes line items that FK to it. A separate command `backport_data_restore` works around this by disabling FK constraints, but duplicates the docs process. Two restore paths is cruft.

The chart of accounts is business data, not Xero-exclusive. Only the `xero_id` (Xero's per-tenant UUID) is environment-specific. Account codes (200=Sales, 300=Purchases) and names are universal.

## Approach

Include XeroAccount in the backup as-is (production `xero_id` values are harmless). Change `sync_accounts` to match by `account_name` (already unique) so Step 16 overwrites `xero_id` with the correct dev value. Plain `loaddata` works, FKs intact throughout. Delete `backport_data_restore`.

### Step 1: `backport_data_backup.py` — include XeroAccount

**File:** `apps/workflow/management/commands/backport_data_backup.py`

- Remove `"workflow.XeroAccount"` from `EXCLUDE_MODELS`

### Step 2: `sync.py` — match by `account_name` instead of `xero_id`

**File:** `apps/workflow/api/xero/sync.py`, function `sync_accounts` (line 933)

Change from:
```python
XeroAccount.objects.update_or_create(
    xero_id=account.account_id,
    defaults={
        "account_code": account.code,
        "account_name": account.name,
        ...
    },
)
```

To:
```python
XeroAccount.objects.update_or_create(
    account_name=account.name,
    defaults={
        "xero_id": account.account_id,
        "account_code": account.code,
        ...
    },
)
```

This means Step 16 (sync chart of accounts) matches existing rows by name and fills in the correct dev `xero_id`. FKs from line items are never broken.

### Step 3: Delete `backport_data_restore.py`

**File:** `apps/job/management/commands/backport_data_restore.py` — delete

No longer needed. Plain `loaddata` works.

### Step 4: Regenerate `__init__.py`

```bash
python scripts/update_init.py
```

### Step 5: Update `AGENTS.md`

Remove `# or backport_data_restore` comment (line 30).

### Step 6: Revert docs to plain `loaddata`

Undo the earlier changes to `docs/restore-prod-to-nonprod.md` — restore original step numbering and use plain `loaddata` with the `.json` file (Step 4 gunzip + Step 5 loaddata).

## Files to modify
- `apps/workflow/management/commands/backport_data_backup.py` — remove XeroAccount from EXCLUDE_MODELS
- `apps/workflow/api/xero/sync.py` — match by account_name
- `apps/job/management/commands/backport_data_restore.py` — delete
- `apps/job/management/commands/__init__.py` — regenerate
- `AGENTS.md` — remove comment
- `docs/restore-prod-to-nonprod.md` — revert to original

### Bug: `_table_exists` / `_column_exists` use DB name instead of schema name

**File:** `apps/workflow/management/commands/seed_xero_from_database.py`

`_table_exists` and `_column_exists` query `information_schema` with `table_schema = DB_NAME` (e.g. `dw_msm_dev`). But `table_schema` should be `'public'`. This causes every check to return `False`, so `clear_production_xero_ids` silently skips all tables and clears nothing.

Fix: Change both methods to use `'public'` instead of `settings.DATABASES["default"]["NAME"]`.

### Deferred: Seed accounting documents to dev Xero

Invoices, bills, quotes, credit notes have stale production `xero_id` values. The seed should push them to dev Xero and overwrite `xero_id`. This is a separate PR — for now, skip the accounting tables in `clear_production_xero_ids` (they'll fail on NOT NULL anyway, but the `_table_exists` fix means they'll now be attempted).

**Workaround for this PR:** Remove the accounting tables from the clear step so the seed doesn't error. The stale xero_ids are harmless until the accounting seed PR lands.

## Verification

1. Reset DB, migrate, `loaddata` the new backup — should succeed (XeroAccount fix)
2. Run `seed_xero_from_database` — should clear client/job/stock/PO Xero IDs without error
3. Run `start_xero_sync` — should complete without the "Demo Company Shop" conflict
