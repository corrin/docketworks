# Fix: Xero API calls hang silently on rate limit (429)

## Context

`seed_xero_from_database --only invoices` hangs for 10+ minutes with no output. Debug script (`scripts/debug_xero_fetch.py`) proved **every** Xero API call hangs — even `get_accounts`.

Traceback shows urllib3 sleeping silently on `Retry-After` header. With urllib3 retry disabled, we captured the actual 429 response:

```
Retry-After: 66183                  # 18.4 hours
X-Rate-Limit-Problem: day           # daily limit hit
X-DayLimit-Remaining: 0
X-MinLimit-Remaining: 60
X-AppMinLimit-Remaining: 9998
```

urllib3's default `Retry` config silently sleeps for the `Retry-After` duration with zero logging.

## This PR

Fix 429 handling + fix the seed + full restructure of xero module. All in one.

### 1. Subclass RESTClientObject for rate-limit-aware API calls

**New file:** `apps/workflow/api/xero/client.py` (~50 lines)

Subclass `xero_python.rest.RESTClientObject`. Override `request()` to:
- Disable urllib3 silent retry (`Retry(0, respect_retry_after_header=False)`)
- Enforce minimum 1s sleep between calls
- Log quota remaining on every successful response (`X-DayLimit-Remaining`, `X-MinLimit-Remaining`)
- Catch 429 responses: log the rate limit type and `Retry-After` value. For minute limits, sleep and retry. For day limits, `persist_app_error` and raise.

**File:** `apps/workflow/api/xero/xero.py` (~line 35)

After `api_client = ApiClient(...)`, swap in the subclass:
```python
from apps.workflow.api.xero.client import RateLimitedRESTClient
api_client.rest_client = RateLimitedRESTClient(api_client.configuration)
```

This catches every Xero call made through `api_client` — sync, seed, views, everything. No other files need to change for 429 handling.

### 2. Move seed fetch into sync.py as `fetch_xero_entity_lookup()`

**File:** `apps/workflow/api/xero/sync.py` (above `ENTITY_CONFIGS`, ~line 1177)

Reuses `ENTITY_CONFIGS` for API method resolution, pagination, and params. Returns `{key_func(item): value_func(item)}` dict. Also extract `_resolve_api_method()` from `sync_all_xero_data` so both functions share it.

### 3. Update seed command to use `fetch_xero_entity_lookup`

**File:** `apps/workflow/management/commands/seed_xero_from_database.py`

- Import `fetch_xero_entity_lookup` from `apps.workflow.api.xero.sync`
- Replace `_fetch_existing_xero_invoices` call with `fetch_xero_entity_lookup("invoices", ...)`
- Replace `_fetch_existing_xero_quotes` call with `fetch_xero_entity_lookup("quotes", ...)`
- Delete `_fetch_existing_xero_invoices` and `_fetch_existing_xero_quotes` methods
- Delete `--limit` argument and `self._limit` usage

### 4. Fix xero.py scope handling

The `isinstance` fallbacks in `refresh_token` (line 178) and `exchange_code_for_token` (line 303) need a test first to prove whether the current code is wrong before changing it.

## Verification

1. Run `scripts/debug_xero_fetch.py` — should log rate limit warning with `X-Rate-Limit-Problem: day` and `Retry-After: N` instead of hanging silently
2. Wait for daily rate limit to reset, then run `python manage.py seed_xero_from_database --only invoices --skip-clear` — should complete with quota logging on every call
3. Log output should show `X-DayLimit-Remaining` decreasing on each call

## Files to modify

- `apps/workflow/api/xero/client.py` — **new**, RESTClientObject subclass
- `apps/workflow/api/xero/xero.py:35` — swap in subclass
- `apps/workflow/api/xero/sync.py:1177` — add `fetch_xero_entity_lookup`, extract `_resolve_api_method`
- `apps/workflow/management/commands/seed_xero_from_database.py` — use new function, delete old methods

### 5. Full restructure of xero module

Current state: ~12,000 lines across 14 files, Xero SDK calls scattered. MYOB customer enquiry makes centralisation critical.

Split by responsibility:

| File | Responsibility | Lines | Source |
|------|---------------|-------|--------|
| `auth.py` | Token, tenant, OAuth flow | ~340 | `xero.py:1-355` |
| `client.py` | Rate-limited REST client | ~50 | New (step 1 above) |
| `transforms.py` | All transform_* functions | ~760 | `sync.py:59-820` |
| `sync.py` | Sync engine + ENTITY_CONFIGS + cursors | ~500 | `sync.py:954-1415` |
| `push.py` | Push local→Xero (jobs, contacts, costlines) | ~800 | `sync.py:1488-1940` + `xero.py:357-750` |
| `seed.py` | Seed helpers + fetch_entity_lookup | ~200 | `sync.py:2035-2215` + new (step 2 above) |
| `reprocess.py` | Field extraction from raw_json | ~565 | `reprocess_xero.py` (rename) |
| `payroll.py` | Payroll API | ~2210 | Unchanged |
| `stock_sync.py` | Stock sync | ~513 | Unchanged |

Update all imports across the codebase. Run `python scripts/update_init.py` to regenerate `__init__.py`.
