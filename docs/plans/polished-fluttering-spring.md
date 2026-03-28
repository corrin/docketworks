# Fix XeroPayItem Backup/Restore

## Context

`loaddata` fails because Jobs reference prod XeroPayItem UUIDs that don't exist on dev. See `docs/plans/xero-pay-item-backup-problem.md` for full analysis.

## Approach

1. Include XeroPayItem in the backup with xero_id/xero_tenant_id set to null
2. Make xero_id and xero_tenant_id nullable (aligns with every other Xero ID in the system)
3. Remove the useless migration seeds
4. Clean up the broken remap code in seed_xero_from_database

## Changes (already done)

### `apps/workflow/management/commands/backport_data_backup.py`
- Added `workflow.XeroPayItem` to INCLUDE_MODELS
- Sanitizes xero_id/xero_tenant_id after dump (currently sets placeholders — will change to null)

### `apps/workflow/migrations/0187_create_xero_pay_item.py`
- Removed seed creation function and RunPython call
- Kept CreateModel (table still needed)

### `apps/workflow/management/commands/seed_xero_from_database.py`
- Removed `process_pay_items` and `pay_items` entity
- Added XeroPayItem clearing to `clear_production_xero_ids` (currently sets placeholders — will change to null)

### `apps/workflow/models/xero_pay_item.py`
- Made `xero_id` and `xero_tenant_id` nullable
- Add comment explaining why: records are loaded from backup without Xero IDs, which get populated when the target environment connects to its own Xero via `xero --configure-payroll`

## Changes (still needed)

### Add post-sync validation to `sync_xero_pay_items()` in `apps/workflow/api/xero/payroll.py`
After syncing leave types and earnings rates, check for XeroPayItem records referenced by Jobs/CostLines that still have null xero_ids. These are pay items from the backup that weren't matched by name during Xero sync. Raise an error listing the unmatched pay items instead of reporting success.

### Move seeds from migration 0187 to a fixture
Seeds don't belong in a migration — they're data, not schema. Follow the existing pattern (`company_defaults.json`, `ai_providers.json`).

1. **Create `apps/workflow/fixtures/xero_pay_items.json`**
   - Same 7 pay items currently in migration 0187
   - `xero_id` and `xero_tenant_id` set to null (filled by `xero --configure-payroll`)

2. **Migration 0187 — already cleaned up** (seeds removed, CreateModel kept)

3. **No restore doc changes** — after DB reset + migrate, table is empty. loaddata loads XeroPayItem from the backup. The fixture is only for fresh installs and tests.

### Deploy to prod
- scp the updated `backport_data_backup.py` to prod (and migration if needed)
- Run `python manage.py backport_data_backup` on prod
- Transfer new backup to dev

## Verification

1. Reset DB, migrate — seeds exist with null xero_ids
2. loaddata with new backup — no FK errors, XeroPayItem records from backup loaded
3. `xero --configure-payroll` — XeroPayItem records get real dev Xero IDs
4. Post-sync validation catches any unmatched pay items
