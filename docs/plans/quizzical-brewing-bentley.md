# Plan: Add `enable_xero_sync` gate to prevent sync before seeding

## Context

After a prod restore, there's a dangerous window between Step 22 (xero --setup, which sets `xero_tenant_id`) and Step 25 completion (seed_xero_from_database). During this window, the database has **production Xero IDs** but is connected to the **dev Xero tenant**. If any sync fires, it would push stale prod references to dev Xero.

The current gate checks `xero_tenant_id`, but that's set as soon as you connect — too early. We need a gate that's only true after seeding completes.

Additionally, the `company_defaults.json` fixture already has a hardcoded `xero_tenant_id`, which would also bypass the current gate immediately on fixture load.

## Changes

### 1. Add `enable_xero_sync` field to CompanyDefaults
**File:** `apps/workflow/models/company_defaults.py`

Add a `BooleanField(default=False)` in the Xero integration section, after `xero_shortcode`. This defaults to `False` so sync is blocked on fresh restores.

### 2. Create migration

### 3. Update fixture
**File:** `apps/workflow/fixtures/company_defaults.json`

Add `"enable_xero_sync": false`. Also remove the hardcoded `xero_tenant_id` value — it's a prod tenant ID sitting in a dev fixture, which is exactly the kind of thing this gate is meant to prevent.

### 4. Replace gate in sync
**File:** `apps/workflow/api/xero/sync.py` (~line 1293-1297)

Change the check from:
```python
if not company.xero_tenant_id:
```
to:
```python
if not company.enable_xero_sync:
```

Update the warning message to reference `seed_xero_from_database`.

### 5. Set flag at end of seed command
**File:** `apps/workflow/management/commands/seed_xero_from_database.py` (~line 113)

After "Xero seeding complete!", set:
```python
company = CompanyDefaults.get_solo()
company.enable_xero_sync = True
company.save()
```

Only when `dry_run` is False.

### 6. Update docs
**File:** `docs/backup-restore-process.md`

Update Step 22's description to note that sync is gated by `enable_xero_sync`, not `xero_tenant_id`. No step changes needed — the flow stays the same.

## Verification

1. `python manage.py makemigrations workflow` — creates migration
2. `python manage.py migrate` — applies it
3. `python manage.py loaddata apps/workflow/fixtures/company_defaults.json` — loads with `enable_xero_sync=False`
4. Verify gate: `python manage.py start_xero_sync` should warn and exit without syncing
5. `python manage.py seed_xero_from_database --dry-run` — should NOT set the flag
6. After real seed completes, `enable_xero_sync` should be `True` and sync should work
