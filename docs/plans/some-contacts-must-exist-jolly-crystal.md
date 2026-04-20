# Add `allow_jobs` field to Client to block job creation for admin-only contacts

## Context

Some Xero Contacts must exist in the system for accounting reasons (tax authorities, internal accounts, payroll liability accounts, government bodies, etc.) but must **never** be selected as the Client on a Job. Today the Client model has no field that represents this intent:

- `xero_archived` mirrors Xero's `ContactStatus=ARCHIVED` — these contacts are *active* in Xero, not archived.
- `merged_into` / `xero_merged_into_id` only track Xero merges.
- `is_supplier` can't be overloaded — a supplier can legitimately also be a job client.
- `is_account_customer` is a payment-terms flag, not an eligibility flag.

Equally important, **even the existing semantically-adjacent flags aren't enforced**: `JobRestService.create_job()` (`apps/job/services/job_rest_service.py:246`) happily creates a job for any Client row, and `ClientRestService._execute_client_search()` (`apps/client/services/client_rest_service.py:517`) returns every matching row including archived/merged ones. Fixing that gap belongs in this change — otherwise we'd ship a new field while the old ones stay unenforced and the picker keeps offering archived/merged clients.

Intended outcome: a dedicated `allow_jobs` boolean on `Client` (default `True`) as the **single enforcement flag** for job-eligibility. The Xero archive and merge pipelines flip `allow_jobs=False` automatically, so one filter and one guard clause cover all three cases (admin-only contacts, Xero-archived, Xero-merged). The picker and `create_job` service both respect the flag.

## Approach

Single new boolean field, enforced in two backend places, toggleable from the Client edit UI, and automatically set by the two existing code paths (Xero archive, Xero merge) that today produce clients-that-shouldn't-be-picked.

Key design decisions:
- **`allow_jobs` is the single enforcement flag.** The picker and `create_job` only look at this one field. `xero_archived` and `merged_into` stay as diagnostic/reporting fields (they tell you *why* a client is ineligible); they are not consulted by the enforcement code paths.
- **Archive/merge events flip `allow_jobs=False` once.** The flag does not auto-revert if a client is un-archived in Xero — a human should make that call, because un-archival in Xero doesn't necessarily mean the contact is now appropriate for job assignment. This matches the CLAUDE.md "fail early, no fallbacks, one way to do everything" philosophy: one field, one code path, explicit human action to re-enable.
- **Not Xero-sourced in the normal sync-field sense.** `allow_jobs` is set *by* Xero sync events as a side effect but is not a mirror of a single Xero field. So it does not belong in `CLIENT_DIRECT_FIELDS`' Xero round-trip or in `get_client_for_xero()`.

## Backend changes

### 1. Model — `apps/client/models.py`

- Add field after `is_supplier` (line 62), grouped with the other policy booleans:
  ```python
  allow_jobs = models.BooleanField(
      default=True,
      help_text="If False, this client cannot be selected as the client on a Job. "
                "Use for Xero contacts that must exist (tax authorities, internal "
                "accounts, etc.) but should never appear on a job.",
  )
  ```
- Add `"allow_jobs"` to `CLIENT_DIRECT_FIELDS` (line 24).
- Update the checklist comment at lines 13–21 — the field needs to appear in `_format_client_detail`, the detail serializer, and the update path. It does **not** belong in `update_client_from_raw_json` (not Xero-sourced) or in `get_client_for_xero` (not sent to Xero).

### 2. Migration

Two-step migration:

1. **Schema migration** — `python manage.py makemigrations client`. Produces an `AddField` with `default=True`.
2. **Data migration** (new, hand-written `RunPython` in the same or a follow-up migration) — for every existing client where `xero_archived=True` OR `merged_into_id IS NOT NULL`, set `allow_jobs=False`. This retroactively applies the new enforcement to clients that were already archived/merged before this feature landed. Pattern mirrors the existing data migration at `apps/client/migrations/0004_populate_merge_fields.py:62-78`.

The reverse migration is a no-op (field removal drops everything).

### 3. Enforcement in job creation — `apps/job/services/job_rest_service.py:268-271`

Immediately after the `Client.objects.get(...)` lookup, before building `job_data`:

```python
if not client.allow_jobs:
    raise ValueError(
        f"Client '{client.name}' is not permitted for jobs. "
        f"Update the client to allow jobs if this is wrong."
    )
```

This is the defense-in-depth layer — the picker won't offer these, but a direct POST with a blocked `client_id` must still fail cleanly rather than silently creating a job.

### 4. Filter out of client search — `apps/client/services/client_rest_service.py:517-549`

Add `.filter(allow_jobs=True)` to `_execute_client_search`. The picker (`useClientLookup.searchClients` → `api.clients_search_retrieve`) is the only consumer of this endpoint, so the exclusion is safe and desirable. Clients management/admin views use different endpoints (`ClientsView.vue` uses the full list), so admins can still find and edit blocked clients.

### 5. Serializers — `apps/client/serializers.py`

Add `allow_jobs = serializers.BooleanField(...)` in the four places that currently list `is_account_customer` (lines 111, 137, 172, 198). Match the `required` / `default` conventions of each: `default=True` on create, `required=False` on update, present on detail/search responses.

### 6. Detail formatter — `apps/client/services/client_rest_service.py`

Add `"allow_jobs": client.allow_jobs` to `_format_client_detail`. Do **not** add to `_format_client_summary` — the search endpoint already filters them out, so summary consumers don't need the flag. (Exception: if we later want the admin Clients list to show a badge, revisit then.)

### 7. Xero archive hook — `apps/workflow/api/xero/reprocess_xero.py:205-206`

Extend the existing archive detection so that when `contact_status == "ARCHIVED"` is applied, `allow_jobs` is also forced to `False`:

```python
if contact_status == "ARCHIVED":
    client.xero_archived = True
    client.allow_jobs = False
```

### 8. Xero merge hook — `apps/workflow/api/xero/transforms.py:899-903` and `apps/workflow/api/xero/seed.py:150-154`

At both sites where `client.merged_into = merged_into` is set, also set `client.allow_jobs = False` on the merged-from client. These are the only two places merge resolution happens; both need the same one-line addition. (The `xero_merged_into_id` field in `reprocess_xero.py:210-211` is set before the `Client` FK is resolved, so the `allow_jobs` flip correctly belongs next to the FK assignment, not there.)

## Frontend changes

### 9. Regenerate API types

After the backend lands: `cd frontend && npm run update-schema && npm run gen:api`.

### 10. Client edit UI — `frontend/src/views/ClientDetailView.vue`

Add an "Allow jobs" checkbox (or toggle) next to the existing `is_account_customer` / `is_supplier` controls. Wire it to the same update path used by those fields. Default on for new clients via `CreateClientModal.vue`. When the flag is off because of Xero archival or a merge, show a read-only indicator stating why (using the existing `xero_archived` / `merged_into` fields) so an admin understands before re-enabling.

### 11. Picker — no change required

`useClientLookup.ts` just re-displays whatever the search endpoint returns. Backend filtering at step 4 is sufficient; adding a second filter layer on the frontend would only drift from the backend.

## Files to modify

| File | Change |
|---|---|
| `apps/client/models.py` | Add `allow_jobs` field; update `CLIENT_DIRECT_FIELDS` and checklist comment |
| `apps/client/migrations/<next>.py` | Auto-generated `AddField` + hand-written `RunPython` backfill for already-archived/merged clients |
| `apps/job/services/job_rest_service.py` | Raise `ValueError` in `create_job` when `client.allow_jobs` is False |
| `apps/client/services/client_rest_service.py` | Filter `allow_jobs=True` in `_execute_client_search`; expose field in `_format_client_detail` |
| `apps/client/serializers.py` | Add `allow_jobs` to the four client serializers alongside `is_account_customer` |
| `apps/workflow/api/xero/reprocess_xero.py` | Set `allow_jobs=False` when Xero marks contact ARCHIVED |
| `apps/workflow/api/xero/transforms.py` | Set `allow_jobs=False` on merged-from client when `merged_into` FK is resolved |
| `apps/workflow/api/xero/seed.py` | Same merge-time flip as `transforms.py` |
| `frontend/src/api/generated/api.ts` | Regenerated — do not hand-edit |
| `frontend/src/views/ClientDetailView.vue` | Add "Allow jobs" toggle plus read-only "blocked because archived/merged" indicator |
| `frontend/src/components/CreateClientModal.vue` | Default the new field to `true` on create |

## Reused patterns

- Field shape and serializer treatment: follow `is_account_customer` exactly (model default, serializer placement, frontend toggle position).
- Validation style in `create_job`: matches the existing `raise ValueError("Client is required")` guard clauses at `apps/job/services/job_rest_service.py:262-271`.
- Search filter layering: same `.filter().annotate().only()` chain already in place at `apps/client/services/client_rest_service.py:523-548`.

## Verification

1. **Migration round-trip + backfill**
   - Before migrating, note the counts: `Client.objects.filter(xero_archived=True).count()` and `Client.objects.exclude(merged_into=None).count()`
   - `python manage.py makemigrations client` → inspect generated migration, add `RunPython` backfill
   - `python manage.py migrate`
   - After migrating: `Client.objects.filter(allow_jobs=False).count()` should equal (archived ∪ merged) count from before
   - `python manage.py migrate client <prev>` then forward again — confirms reversibility
2. **Backend unit-level smoke (Django shell)**
   - Pick a non-job contact (e.g. an IRD/tax-authority entry), set `allow_jobs=False`, save
   - `JobRestService.create_job({"name": "test", "client_id": <that id>}, user)` → expect `ValueError`
   - `ClientRestService._execute_client_search("<substring of that name>", 20)` → expect that client **not** in results
   - Same two checks against a known archived client and a known merged-from client → both should be blocked/hidden
   - Confirm a regular client with `allow_jobs=True` still creates a job and still shows up in search
3. **Xero-sync hook verification**
   - Pick a test client in Xero, archive it in the Xero UI, run the Xero sync → confirm `allow_jobs` flips to `False` on the Docketworks side
   - Merge a test client into another in Xero, sync → confirm the merged-from client has `allow_jobs=False` and `merged_into` set
4. **Frontend end-to-end via ngrok URL from `.env`**
   - Navigate to the blocked client's detail page → toggle "Allow jobs" off → save
   - On the New Job modal, search for that client by name → confirm it does not appear in suggestions
   - On the same modal, search for a normal client → confirm it still appears and a job can be created
   - Flip the blocked client back to "Allow jobs" on → confirm it reappears in the picker
   - On an archived/merged client's detail page, confirm the read-only "blocked because archived/merged" indicator is shown
5. **Regression sweep**
   - `npm run type-check` in `frontend/`
   - Existing client E2E tests still pass (`frontend/tests/` — grep for `client` specs)
