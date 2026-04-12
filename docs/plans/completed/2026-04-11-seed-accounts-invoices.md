# Seed accounts + invoices in seed_xero_from_database

## Context

After a prod restore, XeroAccount records have prod `xero_id` values. The dev Xero has the same accounts (same names/codes) but different `xero_id` UUIDs. The seed command should reconcile these by fetching accounts from dev Xero and upserting by `account_name`, updating `xero_id` to the dev value. This replaces the separate Step 17 in the restore docs.

## Changes

### 1. Add accounts phase to `seed_xero_from_database`
**File:** `apps/workflow/management/commands/seed_xero_from_database.py`

Add `"accounts"` to `VALID_ENTITIES`. Add `process_accounts()` as the first phase (before contacts):
- Fetch all accounts from dev Xero via `AccountingApi.get_accounts()`
- For each Xero account, `XeroAccount.objects.update_or_create(account_name=..., defaults={xero_id=..., ...})`
- This updates prod `xero_id` values to dev values

Run order: **accounts → contacts → projects → invoices → stock → employees**

### 2. Update restore docs
**File:** `docs/restore-prod-to-nonprod.md`

Remove Step 17 (Sync Chart of Accounts). Update Step 19 description to note accounts sync is now included. Renumber.

### 3. DB reset + restore + test
1. DROP SCHEMA / CREATE SCHEMA
2. migrate
3. loaddata prod backup
4. Steps 7-14
5. Xero OAuth
6. xero --setup, xero --configure-payroll
7. seed_xero_from_database (now handles accounts + invoices)

## Verification
1. After seed, XeroAccount records should have dev `xero_id` values
2. `start_xero_sync` (step 20) should run without account conflicts
3. Invoice dry-run shows 1,237 job-linked invoices
4. Full run creates invoices in dev Xero
