# Code Review Fixes: DRY, Fail Early, Trust the Data Model

## Context

Code review found the `XeroAccountingProvider` has massive DRY violations, missing `persist_app_error` calls, defensive code that doesn't trust the data model, and a `is_accounting_enabled()` that silently swallows errors. This plan fixes all review findings.

## File: `apps/workflow/accounting/xero/provider.py`

### DRY: Extract shared helpers

Every document method repeats the same 4-line import block, 2-line API setup, and 7-line error handler. Extract:

**`_get_api()`** — returns `(api, tenant_id)` tuple:
```python
def _get_api(self):
    from apps.workflow.api.xero.auth import api_client, get_tenant_id
    from xero_python.accounting import AccountingApi
    return AccountingApi(api_client), get_tenant_id()
```

**`_to_xero_payload(xero_object)`** — the `convert_to_pascal_case(clean_payload(...))` pattern used everywhere:
```python
@staticmethod
def _to_xero_payload(xero_object):
    from apps.workflow.views.xero.xero_helpers import clean_payload, convert_to_pascal_case
    return convert_to_pascal_case(clean_payload(xero_object.to_dict()))
```

**`_build_line_items(payload_line_items)`** — the LineItem list comprehension repeated 4 times:
```python
@staticmethod
def _build_line_items(payload_line_items):
    from xero_python.accounting.models import LineItem
    return [
        LineItem(
            description=li.description,
            quantity=float(li.quantity),
            unit_amount=float(li.unit_amount),
            account_code=li.account_code,
            item_code=li.item_code,
        )
        for li in payload_line_items
    ]
```

**`_make_error_result(exc)`** — the error DocumentResult construction repeated 7 times:
```python
@staticmethod
def _make_error_result(exc):
    from apps.workflow.accounting.types import DocumentResult
    from apps.workflow.views.xero.xero_helpers import parse_xero_api_error_message
    error_msg = str(exc)
    if hasattr(exc, "body"):
        error_msg = parse_xero_api_error_message(exc.body, error_msg)
    return DocumentResult(
        success=False,
        error=error_msg,
        status_code=getattr(exc, "status", 500),
    )
```

### Fail early: `update_purchase_order`

Currently returns a `DocumentResult(success=False)` when `external_id` is None. Should raise `ValueError` — a missing ID is a programming error, not a user error.

### Trust the data model: `get_account_code`

Currently wraps `XeroAccount.objects.get()` in try/except for `DoesNotExist` and returns None. The Sales and Purchases accounts are seeded from Xero — if they're missing, that's a data problem that should crash, not silently return None.

### Missing `persist_app_error`: contacts

`create_contact` and `update_contact` except blocks — already fixed in previous edit, verify they're there.

### `search_contact_by_name`: use Xero API filtering

Currently fetches ALL contacts then iterates. Use the Xero API's `where` filter:
```python
def search_contact_by_name(self, name: str) -> ContactResult | None:
    from apps.workflow.api.xero.auth import api_client, get_tenant_id
    from xero_python.accounting import AccountingApi
    api, tenant_id = self._get_api()
    response = api.get_contacts(tenant_id, where=f'Name=="{name}"')
    contacts = getattr(response, "contacts", [])
    if not contacts:
        return None
    return ContactResult(success=True, external_id=str(contacts[0].contact_id), name=contacts[0].name)
```

## File: `apps/workflow/accounting/registry.py`

### `is_accounting_enabled()`: trust the singleton

`CompanyDefaults` is a singleton — `get_solo()` always returns an instance. No None check, no try/except.

```python
def is_accounting_enabled() -> bool:
    from apps.workflow.models import CompanyDefaults
    return CompanyDefaults.get_solo().enable_xero_sync
```

## File: `apps/workflow/accounting/types.py`

### Missing `date` import

Add `from datetime import date` — used in type annotations for `InvoicePayload`, `QuotePayload`, `POPayload`.

## File: `apps/workflow/views/xero/xero_helpers.py`

Move `clean_payload` and `convert_to_pascal_case` — actually, keep them where they are. The provider imports them. No change needed.

## Run `python scripts/update_init.py`

The `apps/workflow/accounting/` and `apps/workflow/accounting/xero/` directories need `__init__.py` files generated.

## Verification

- `DJANGO_SETTINGS_MODULE=docketworks.settings python -c "import django; django.setup(); from apps.workflow.accounting.registry import get_provider; p = get_provider(); print(p.provider_name)"`
- `python manage.py test apps/workflow/tests/ --keepdb`
