# XeroPayItem Backup/Restore Problem

## What XeroPayItem Is

XeroPayItem is a reference table mapping pay item concepts (Ordinary Time, Double Time, Annual Leave, etc.) to Xero API identifiers. Each record has:

- **id** (UUID PK) — our internal identifier
- **name** — the pay item concept ("Ordinary Time", "Double Time", etc.)
- **xero_id** — the Xero API identifier for this pay item (unique, NOT NULL) — **varies per Xero environment**
- **xero_tenant_id** — which Xero tenant this belongs to — **varies per Xero environment**
- **multiplier** — rate multiplier (1.0, 1.5, 2.0, etc.)
- **uses_leave_api** — whether it's a leave type or earnings rate

## How It's Referenced

Two models have FK references to XeroPayItem:

- `Job.default_xero_pay_item` — **non-nullable FK**, every job must have one
- `CostLine.xero_pay_item` — nullable FK, set on time entries

These FKs store the XeroPayItem's UUID PK.

## The Backup/Restore Flow

The backup command (`backport_data_backup`) dumps business data (Jobs, CostLines, Clients, Staff, etc.) from production for restore onto dev/UAT environments. It deliberately **excludes** Xero-specific models because Xero IDs are environment-specific.

The restore flow:
1. `migrate` — creates empty tables
2. `loaddata` — loads the backup JSON
3. ... (various setup steps) ...
4. `xero --configure-payroll` — syncs XeroPayItem records from the target environment's Xero
5. `seed_xero_from_database` — clears prod Xero IDs from clients/jobs/stock/etc and re-links to the target Xero

## The Bug

`loaddata` fails at step 2 because:
- The backup contains Job records with `default_xero_pay_item` pointing to production XeroPayItem UUIDs
- Those XeroPayItem records don't exist in the dev database
- PostgreSQL enforces the FK constraint → crash

```
django.db.utils.IntegrityError: insert or update on table "workflow_job" violates foreign key constraint
DETAIL: Key (default_xero_pay_item_id)=(3829750d-...) is not present in table "workflow_xeropayitem".
```

## Why Migration 0187's Seeds Made This Worse

Migration 0187 creates 7 "seed" XeroPayItem records with placeholder values (`xero_id='seed-ordinary-time'`, `xero_tenant_id='pending-sync'`). These were created so that migration 0064 (which added the non-nullable `default_xero_pay_item` FK to Job) would have something to point existing jobs to.

That migration has already run on production. On prod, the seeds were subsequently replaced/overwritten by real Xero-synced records with real `xero_id` values. The seeds served a one-time migration purpose and are now useless.

On dev/UAT after `migrate`, the seeds exist with random UUIDs as PKs. These don't match the production UUIDs in the backup, so the FKs still don't resolve. The seeds actively make the problem worse — they create XeroPayItem records that nothing references, while the actual FK targets are missing.

## The Existing Remap Attempt

`seed_xero_from_database` has a `process_pay_items` method that tries to fix orphaned FKs after restore. It:
1. Finds Jobs/CostLines whose `xero_pay_item` FK points to a non-existent XeroPayItem
2. Tries to guess the correct pay item by matching **job names** to pay item names (e.g., a job named "Annual Leave" → pay item "Annual Leave")
3. Defaults everything else to "Ordinary Time"

This is fragile and lossy — a CostLine for "Double Time" on a regular job would incorrectly get mapped to "Ordinary Time" because the job name doesn't match any pay item.

But more importantly: **this code can never run** because `loaddata` crashes before we get to this step.

## What Production's XeroPayItem Table Looks Like

Production has 28 XeroPayItem records synced from Xero. The 5 referenced by jobs in the backup are:

| PK (UUID) | Name | xero_id (prod Xero) |
|---|---|---|
| 3829750d-... | Ordinary Time | 39959181-... |
| 90909bb3-... | Annual Leave | 2392b0c2-... |
| e678e692-... | Sick Leave | e5754ce7-... |
| b58930e0-... | Unpaid Leave | 71d7dc03-... |
| c4848bba-... | Bereavement Leave | 6633aeda-... |

The remaining 23 are other NZ pay items (Holiday Pay, Parental Leave variants, Salary, Allowance, ACC, etc.).

## What Dev's XeroPayItem Table Looks Like After Migrate

7 seed records with:
- Random UUIDs as PKs (don't match any prod UUIDs)
- `xero_id` = `'seed-ordinary-time'`, `'seed-double-time'`, etc.
- `xero_tenant_id` = `'pending-sync'`

## Constraints

- `xero_id` is `unique=True` and `NOT NULL` on the model
- `Job.default_xero_pay_item` is a non-nullable FK
- Cannot deploy code changes to production before the next backup (need a solution that works with the current prod codebase for the backup side, OR a way to fix the backup after it's been taken)
- The solution must work for future clients with different Xero environments (different xero_ids for the same pay item concepts)

## What Needs To Happen

The fundamental requirement: after restore, Jobs and CostLines must reference XeroPayItem records that exist in the dev database and have the correct **names** (the name carries the semantic meaning; the xero_id gets updated when connecting to the target Xero environment).

The `xero_id` and `xero_tenant_id` values from production are meaningless on dev — they belong to prod's Xero app. They need to be blanked/replaced when the target environment connects to its own Xero.
