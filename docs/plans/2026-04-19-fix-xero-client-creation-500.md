# Fix: Client creation 500 (xero_contact_id becomes `True`)

## Context

Creating a client via `POST /clients/` returns 500. The Xero contact is created successfully, but response serialization rejects `xero_contact_id` because it contains the Python boolean `True` instead of a UUID string.

Prod's diagnosis is correct. Validated every step in the chain:

1. **`apps/workflow/api/xero/push.py:452-477`** — `create_client_contact_in_xero(client)` does the right thing at lines 471-472 (sets the real UUID on `client.xero_contact_id` and saves it), but line 473 returns `True` instead of the UUID. The function's implicit contract (it's consumed by a provider that wraps the return value into `ContactResult.external_id`) demands the external ID string.
2. **`apps/workflow/accounting/xero/provider.py:124-137`** — `XeroAccountingProvider.create_contact` assigns `xero_contact_id = create_client_contact_in_xero(client)` (so `xero_contact_id = True`) and packs that into `ContactResult(external_id=True, success=True, name=client.name)`.
3. **`apps/client/services/client_rest_service.py:648-650`** — After `push.py` already persisted the real UUID, the service does `client.xero_contact_id = result.external_id` (overwriting in-memory UUID with `True`) and `client.save(update_fields=["xero_contact_id"])` — Django casts `True` to the literal string `"True"` in the `varchar` column.
4. **`_format_client_summary` (`client_rest_service.py:552-575`)** — `"xero_contact_id": client.xero_contact_id or ""` passes `True` through because `True or ""` is `True` (the in-memory attribute, not re-read from DB).
5. **`ClientCreateResponseSerializer` → `ClientSearchResultSerializer.xero_contact_id` (`apps/client/serializers.py:113`)** is `CharField(allow_blank=True)` — rejects `True` with `"Not a valid string."`.

### Additional defects in the same function

The same function has two more violations of project rules. They are not separate bugs to defer — they are the reason the broken-return-value bug was silent for so long, and they must be fixed together:

- **Exception swallowing (push.py:475-477)** — the `except Exception` branch logs and returns `False`. This violates `CLAUDE.md`'s MANDATORY ERROR PERSISTENCE rule (`persist_app_error(exc)` is required in every exception handler) and the `feedback_never_remove_error_paths` + `feedback_no_fallbacks` memories. The provider at `provider.py:135-137` already does `persist_app_error(exc)` + `return ContactResult(success=False, error=...)` — but it never gets a chance because push.py swallows the exception first.
- **False-on-validation-failure returns (push.py:456, 463)** — when `validate_for_xero()` returns false or `get_client_for_xero()` yields no data, the function returns `False`. The provider then builds `ContactResult(success=True, external_id=False)` — a lying success. The service clobbers the local row with `False → 'False'`, and the caller believes the push worked. Same class of bug as the reported 500, just with a different boolean.

`xero_contact_id` is `unique=True` (`apps/client/models.py:46-48`), so after the first damaged row any second client creation attempt would IntegrityError on the service's redundant `save()` before reaching the serializer. Prod damage is almost certainly **one** row, with `xero_contact_id = 'True'` (and possibly `'False'` too, from a separate silent-failure path).

Sole direct caller of `create_client_contact_in_xero` is `provider.py:129`. `sync.py:21` re-exports it (`# noqa: F401`) without calling. Changing the return contract is safe.

## Fix

All three changes together — they are the same contract repair.

### 1. `apps/workflow/api/xero/push.py:452-477` — rewrite `create_client_contact_in_xero`

Make the contract coherent: success returns the UUID string, any failure raises so the provider's existing `try/except + persist_app_error` can handle it.

```python
def create_client_contact_in_xero(client):
    """Create a single client as Xero contact. Returns xero_contact_id on success, raises on failure."""
    if not client.validate_for_xero():
        raise ValueError(f"Client {client.id} failed Xero validation")

    accounting_api = AccountingApi(api_client)
    contact_data = client.get_client_for_xero()

    if not contact_data:
        raise ValueError(f"Client {client.id} failed to generate Xero data")

    response = accounting_api.create_contacts(
        get_tenant_id(), contacts={"contacts": [contact_data]}
    )
    time.sleep(SLEEP_TIME)

    client.xero_contact_id = response.contacts[0].contact_id
    client.save(update_fields=["xero_contact_id"])
    return client.xero_contact_id
```

Key points:
- Return the UUID string, not `True`.
- Raise `ValueError` on validation/data-generation failure (was silent `return False`).
- Remove the `try/except Exception` — let the Xero SDK's exceptions propagate. The provider at `provider.py:135-137` already catches and calls `persist_app_error(exc)`, which is what the project rule requires. Adding another handler here would double-persist.

### 2. `apps/client/services/client_rest_service.py:648-650` — delete redundant save

`push.py` already persisted the real UUID on the in-memory `client` object. Re-assigning `result.external_id` back onto it is what caused the boolean to reach the DB in the first place.

```python
# lines 648-650 — delete entirely
-        # Save external ID from the accounting provider
-        client.xero_contact_id = result.external_id
-        client.save(update_fields=["xero_contact_id"])
```

### 3. Nothing else changes

`provider.py:124-137` is already correct after these fixes: `create_client_contact_in_xero` returns the UUID → `ContactResult(success=True, external_id=<uuid>, name=...)`; or raises → provider catches, `persist_app_error(exc)`, returns `ContactResult(success=False, error=str(exc))`. The service at `client_rest_service.py:642-646` already checks `result.success` and raises `ValueError` on failure, which the view handles.

## Data cleanup

Before deploying, size and repair the damage on prod. Run this against prod DB:

```sql
SELECT id, name, xero_contact_id, xero_last_modified
FROM client_client
WHERE xero_contact_id IN ('True', 'False');
```

For each row returned:

1. Query Xero's Contacts API by `Name == <client.name>` to retrieve the real `contact_id`.
2. `UPDATE client_client SET xero_contact_id = '<real-uuid>' WHERE id = '<client_id>';`
3. If Xero has no contact with that name (meaning the Xero-side push also failed, or the contact was since renamed/deleted), `SET xero_contact_id = NULL` and flag for manual review.

Do this as a one-off `manage.py shell` script reusing `provider.search_contact_by_name` (`apps/workflow/accounting/xero/provider.py:154-159`). Not a migration — it's a prod-specific data repair.

## Files to modify

- `apps/workflow/api/xero/push.py` — rewrite `create_client_contact_in_xero` (lines 452-477)
- `apps/client/services/client_rest_service.py` — delete lines 648-650

## Verification

1. **Reproduce first** on UAT: `POST /clients/` with a fresh client name. Confirm 500 + log line `Not a valid string`.
2. **Apply the two code changes.**
3. **Happy path on UAT**: `POST /clients/` with a fresh name. Expect 201; response body `xero_contact_id` is a UUID string; `SELECT xero_contact_id FROM client_client WHERE id = '<new_id>'` returns the same UUID; the contact exists in the Xero demo org with that ID.
4. **Validation-failure path**: POST a client that fails `validate_for_xero()` (e.g. missing required field). Expect non-500 error response (400 via the view's `ValueError` handler), an `AppError` row persisted via `provider.py`'s `persist_app_error`, and no local client row left behind in an inconsistent state.
5. **Xero-side failure path**: simulate a Xero API exception (e.g. temporarily point at an invalid tenant, or mock at the test layer). Expect the exception to propagate to `provider.create_contact`, get persisted once, surface as `ContactResult(success=False, …)`, and the view returns a clean error.
6. **Prod data repair**: run the SELECT above, repair each row, re-run the SELECT to confirm zero rows match.
