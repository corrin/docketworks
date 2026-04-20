# Fix stranded FK records on Xero-merged clients

## Context

When Xero merges client A into client B, our sync correctly sets `A.merged_into = B`, but every FK-holding record (Jobs, Invoices, Bills, CreditNotes, Quotes, PurchaseOrders, SupplierProducts, SupplierPriceLists, ScrapeJobs) stays pointing at A. The `merged_into` pointer then acts as metadata only — it's walked for forward lookups via `Client.get_final_client()` but never cascaded to fix stranded FKs.

Impact in prod today: **14 merged-from clients have 28 stranded jobs** (25 archived, 2 "unusual" test data, 1 live awaiting_approval job on "CASH SALE - MCALPINE HUSSMANN" that was merged into the real McAlpine Hussmann record). Additional stranded invoices/POs/quotes on the same 14 clients aren't counted yet.

Why this matters now: PR #207 adds `allow_jobs=False` on merged clients and removes them from the new-job picker. Post-#207, stranded jobs become effectively invisible — the parent client is hidden in the picker, so users can't find their way back to the absorbed history except via direct URLs or the global jobs list. Fixing the stranding is a prerequisite for #207 being safe to ship.

This is a pre-existing bug, not introduced by #207. `merge_clients` management command does partial reassignment (Jobs only) for a different workflow (local dedup); no Xero-merge reassignment exists.

## Approach

Single atomic reassignment function called at every site where `Client.merged_into` gets set. Data migration backfills existing stranded records.

### 1. New service function

**File:** `apps/client/services/client_merge_service.py` (new — `apps/client/services/` already exists with `client_rest_service.py`).

**Signature:**

```python
def reassign_client_fk_records(source: Client, *, logger_prefix: str = "") -> dict[str, int]:
    """Reassign all FK references from `source` to `source.get_final_client()`.
    Fails if source.merged_into is None. Returns per-model rowcounts."""
```

**Behaviour:**
- Resolves destination via `source.get_final_client()` — reuses existing chain-walking + circular-loop guard at `apps/client/models.py:235-252`.
- If `destination.id == source.id` (non-merged client, or pre-cycle terminal matches source on circular chain): raise `ValueError`. Caller guards with `if client.merged_into`.
- Single `transaction.atomic()` block; all 8 FK updates commit together or not at all.
- Per-model `.update()` for the 7 non-audited tables. **Exception: Job iterates via `for j in Job.objects.filter(client=source): j.client = destination; j.save()`** — preserves `HistoricalRecords` audit trail (Job is the only model with SimpleHistory).
- Logs aggregated counts via the `"xero"` logger (matches `reprocess_xero.py` pattern): `logger.info("%sReassigned %s -> %s: jobs=%d invoices=%d bills=%d credit_notes=%d quotes=%d purchase_orders=%d supplier_products=%d supplier_price_lists=%d scrape_jobs=%d", prefix, source.id, destination.id, ...)`.
- Per CLAUDE.md: wrap in try/except, on any exception call `persist_app_error(exc)` and re-raise. No silent skip.

**Reference pattern:** `apps/purchasing/services/stock_service.py:merge_stock_into()` (lines 16-42) shows the atomic-block + per-ref update idiom — model it on that.

### 2. Wire into merge detection sites

**`apps/workflow/api/xero/transforms.py` (`sync_clients`, ~line 896-906):** After the existing merge-resolution loop that sets `client.merged_into = merged_into`, add a second loop that calls `reassign_client_fk_records(client, logger_prefix="[batch-sync] ")` for each client with a newly-set `merged_into`. Only call if destination exists in our DB (current `.first()`-or-silent-skip behaviour is preserved — add a `logger.warning` in that branch so the deferred case is visible; the next sync pass will reassign once the destination lands).

**`apps/workflow/api/xero/seed.py` (`sync_single_contact`, ~line 148-155):** After `client.save()` with a newly-set `merged_into`, call `reassign_client_fk_records(client, logger_prefix="[webhook] ")`.

### 3. Refactor `merge_clients` management command

**File:** `apps/client/management/commands/merge_clients.py` (lines 104-117).

Replace the hand-rolled `Job.objects.filter(client=client).update(client=primary_client)` with a call to the service. This fixes the same stranded-FK bug for the dedup workflow — free consistency win. Keep the subsequent `client.delete()` — this command's semantic is "hard-merge duplicates", distinct from Xero's "mark merged, keep history", and the user-initiated delete is intentional here. The service itself never deletes.

### 4. Data migration (backfill)

**File:** `apps/client/migrations/0018_reassign_stranded_merged_fks.py` (number depends on merge order with PR #207's `0017_client_allow_jobs`; adjust if #207 lands first).

**Shape:** `RunPython(forward, reverse=RunPython.noop)`. Pattern matches `apps/client/migrations/0004_populate_merge_fields.py` and PR #207's `0017_client_allow_jobs.py`.

**Forward logic:**
1. Use `apps.get_model` to fetch historical versions of all 8 affected models. `get_final_client()` cannot be called on historical Client — inline a 10-line chain-walk with the same `seen` cycle guard (copy from `apps/client/models.py:235-252`).
2. For every client with `merged_into_id IS NOT NULL`, compute destination, run the 8 `.update()` calls, sum counts.
3. Log `"Migration 0018: reassigned N records across M merged clients"` via `logger = logging.getLogger("xero")`.
4. Jobs in the migration use `.update()` (not iterate-and-save) — SimpleHistory audit rows aren't worth the per-row overhead for a one-shot backfill; document this in the migration docstring.

**Reverse:** `RunPython.noop` — the reassigned state is the correct state, no need to un-reassign.

### 5. Tests

**File:** `apps/client/tests/test_client_merge_service.py` (new).

Coverage:
- One test per FK type (8 tests): create source + dest, create record pointing at source, call service, assert FK points at dest.
- Chain case: `A -> B -> C`, create Job on A, call service on A, assert Job lands on C (uses `get_final_client()`).
- Circular chain: `A -> B -> A`, create Job on A, call on A — asserts pre-cycle terminal reached, no infinite loop, warning in log.
- Idempotency: call twice, second call returns all-zero counts, no errors.
- `ValueError` when called on a client with `merged_into=None`.
- SimpleHistory: reassigning a Job creates a new `HistoricalJob` row (per-save path, not `.update()`).

**Migration test:** Pytest fixture that seeds stranded records, applies migration via `django-test-migrations` if the project already uses it, else via `call_command("migrate", "client", "0018", ...)`. Assert counts match.

### 6. Edge cases & non-goals

- **Circular chains**: `get_final_client()` returns the pre-cycle terminal — reassign to that, log a warning. Do not attempt to break the cycle here (separate concern, `data_integrity_service.py` already detects).
- **Unsynced destination** (batch-sync case where merged-into not yet in our DB): preserve current `.first()` skip behaviour; add a `logger.warning`. Next sync pass resolves it.
- **Non-goal**: do NOT delete the merged-from Client row. Keep `merged_into` set; rely on PR #207's `allow_jobs=False` to hide it from the picker.
- **Non-goal**: do NOT touch `ClientContact` or `SupplierPickupAddress` — they cascade on Client, which we are not deleting.
- **Non-goal**: do NOT add SimpleHistory to Client. Out of scope.

## Critical files to modify

| Path | Change |
|---|---|
| `apps/client/services/client_merge_service.py` (new) | `reassign_client_fk_records()` service function |
| `apps/client/migrations/0018_reassign_stranded_merged_fks.py` (new) | Data migration — backfill existing stranded records |
| `apps/workflow/api/xero/transforms.py` | Call service after merge resolution in `sync_clients` |
| `apps/workflow/api/xero/seed.py` | Call service after merge resolution in `sync_single_contact` |
| `apps/client/management/commands/merge_clients.py` | Replace hand-rolled Job reassign with service call |
| `apps/client/tests/test_client_merge_service.py` (new) | Unit tests covering all 8 FK types + chain + circular + idempotency |

## Patterns to reuse

- `Client.get_final_client()` — `apps/client/models.py:235-252` — chain-walking with cycle guard.
- `merge_stock_into()` — `apps/purchasing/services/stock_service.py:16-42` — atomic multi-reference reassignment pattern.
- `persist_app_error(exc)` — `apps/workflow/services/error_persistence.py` — mandatory error capture per CLAUDE.md.
- `apps/client/migrations/0004_populate_merge_fields.py` — data-migration shape.

## Verification

**Before merging:**

1. Unit tests: `pytest apps/client/tests/test_client_merge_service.py` — all pass.
2. Migration applies cleanly locally: `python manage.py migrate client 0018` against a dev DB restored from a prod snapshot. Log line reports expected counts (28 jobs + invoices/POs/quotes from the 14 affected clients).
3. Migration reversal is a no-op: `python manage.py migrate client 0017` succeeds without error, records stay reassigned (correct behaviour).
4. Manual: in a test env, trigger a Xero contact merge via the webhook endpoint, confirm Jobs/Invoices/etc. attached to the merged-from client land on the merged-into client. Verify `merged_into` FK is set and Client row is NOT deleted.
5. Regression: existing `merge_clients` management command still works end-to-end (hard-merge duplicate + delete).

**Post-deploy on prod:**

1. Run the same SQL that found the 28 stranded jobs — it should now return 0 for any jobs on clients where `merged_into IS NOT NULL`:
   ```sql
   SELECT COUNT(*) FROM job_job j
   JOIN client_client c ON j.client_id = c.id
   WHERE c.merged_into_id IS NOT NULL;
   ```
2. Spot-check the McAlpine Hussmann awaiting_approval job — should now appear when viewing the real McAlpine Hussmann client's job list.

## Sequencing / PR order

This PR must land **before** PR #207. #207 adds `allow_jobs=False` filtering that hides merged-from clients from the picker — with stranded FKs in place, those jobs become effectively invisible. This PR fixes that foundation.

## Plan file naming note

User convention (per memory) is `YYYY-MM-DD-description.md`. This file uses the auto-generated name `yes-plan-it-properly-ticklish-muffin.md` imposed by the plan-mode workflow. If renamed after plan approval, suggested name: `2026-04-20-xero-merge-reassign-fks.md`.
