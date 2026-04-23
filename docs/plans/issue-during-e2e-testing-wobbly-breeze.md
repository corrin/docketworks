# Fix: E2E company-defaults staleness via per-request cache invalidation header

## Context

The E2E test `frontend/tests/company-defaults.spec.ts` fails intermittently because of a race across gunicorn workers:

- Multi-worker gunicorn (UAT and prod) caches `CompanyDefaults.get_solo()` per worker via django-solo on `LocMemCache` (`docketworks/settings.py:716-728`, TTL 300s).
- A PATCH lands on worker A, writes the DB, invalidates only worker A's cache. An immediate GET load-balances to worker B/C, which returns its stale singleton (trace showed 29-minute staleness).

E2E runs against **dev, uat, and prod**. The cache must behave like it has a 0ms TTL *only while Playwright is running*, and must return to normal the moment Playwright stops. No server-side `.env` flag, no persistent "E2E mode" — the signal that Playwright is running is "requests are coming in with a specific header."

## Approach

Playwright is configured to attach `X-E2E-Cache-Bypass: 1` to every HTTP request via `playwright.config.ts`'s `use.extraHTTPHeaders`. A small Django middleware invalidates the `CompanyDefaults` solo cache key on the current worker whenever it sees that header. Effect per request, regardless of which worker handles it:

1. Middleware runs first → flushes this worker's `CompanyDefaults` cache.
2. View calls `CompanyDefaults.get_solo()` → miss → fresh DB read.

When Playwright isn't running, no request carries the header, middleware is a no-op, normal cache behavior resumes instantly. No start/end transition, no server state, no DB writes, no new endpoint.

Security: the header only forces a cache invalidation (a cheap SELECT on a singleton). It does not expose any data or grant any privilege. Not worth guarding; leaving unauthenticated-but-present is fine.

## Changes

Three files. No `.env` changes anywhere.

### 1. `apps/workflow/middleware/e2e_cache_bypass.py` (new)

```python
from django.core.cache import cache
from apps.workflow.models import CompanyDefaults


class E2ECacheBypassMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.headers.get("X-E2E-Cache-Bypass") == "1":
            cache.delete(CompanyDefaults.get_cache_key())
        return self.get_response(request)
```

### 2. `docketworks/settings.py`

Register the middleware in `MIDDLEWARE` (anywhere after `AuthenticationMiddleware` is fine; order is not load-bearing since it only deletes a cache key).

**Revert** my previously-staged edits in this file — the `E2E_ENVIRONMENT` env var parsing and the branched `SOLO_CACHE` block. Restore the original `SOLO_CACHE = "default"` + `SOLO_CACHE_TIMEOUT = 300`.

### 3. `frontend/playwright.config.ts`

Add to the `use:` block:

```ts
extraHTTPHeaders: {
  'X-E2E-Cache-Bypass': '1',
},
```

Playwright applies this to both browser-originated XHR/fetch calls and `page.request.*` node-side calls, so every HTTP request in the test suite carries the header.

## Files to revert (previously staged, now wrong design)

- `.env.example` — revert the `E2E_ENVIRONMENT=false` addition.
- `scripts/server/templates/env-instance.template` — revert the `E2E_ENVIRONMENT=__E2E_ENVIRONMENT__` addition.
- `scripts/server/instance.sh` — revert the `E2E_ENVIRONMENT_VALUE` bash logic and the extra `sed -e` substitution.
- `docketworks/settings.py` — revert as described in §2 above (keep only the middleware registration line, not the E2E env flag parsing).

After reverts, re-run `pre-commit run --all-files` — codesight regenerations may differ from the current staged set (since env-var inventory and knowledge map are regenerated from source).

## Out of scope

- **Cross-worker cache coherence for real users** (e.g. DB-backed cache-generation counter, or Redis). This plan fixes the E2E race only. Real operators editing company-defaults in prod can still hit up-to-SOLO_CACHE_TIMEOUT-seconds staleness after save. Flag if that UX concern should be part of this PR — otherwise separate follow-up.

## Delivery

1. Working tree is on `fix/e2e-company-defaults-solo-cache`, branched off `main`. Keep using this branch.
2. Revert the 4 previously-staged files per §"Files to revert".
3. Add middleware (new file) and register it in `settings.py`.
4. Update `frontend/playwright.config.ts`.
5. `pre-commit run --all-files` until green.
6. Commit, push, open PR against `main`.

## Verification

1. **CI must pass**: backend tests + pre-commit. Add a unit test for the middleware — send a request with/without the header, assert the `CompanyDefaults` cache key is/isn't deleted.
2. **Local sanity** (single-process, so race is not reproducible, but header effect is): Django shell — stub a request with the header through the middleware, confirm `cache.get(CompanyDefaults.get_cache_key())` is None after the middleware runs.
3. **UAT E2E**: after deploy, `cd frontend && npx playwright test tests/company-defaults.spec.ts` — both tests pass repeatedly.
4. **Prod cache preserved**: real-user requests don't carry the header, middleware is a no-op, `get_solo()` cache behavior is unchanged from today.
