# Fix Xero OAuth Cancel Error

## Context

When a user clicks Cancel during Xero OAuth login, Xero redirects back with `?error=access_denied&error_description=...` query params. The callback view ignores these and calls `exchange_code_for_token()` with a null code, which POSTs to Xero and gets a 400 back, crashing with an unhandled `HTTPError`.

Additionally, the existing error-path code (when exchange fails) calls `render()` with a template (`xero/error_xero_auth.html`), which doesn't exist. Django is a pure API backend — it must never render HTML templates.

The OAuth callback is a browser-redirect endpoint (not a JSON endpoint), so responses must be `redirect()` calls to the frontend, not JSON or HTML.

## Fix

File: `apps/workflow/views/xero/xero_view.py`

### 1. Early exit on OAuth error (already partially done — needs correction)

My existing edit added an early check but used `render()`. Replace it with a `redirect()` to the frontend login URL with an error query param:

```python
error = request.GET.get("error")
if error:
    error_description = request.GET.get("error_description", error)
    logger.info(f"Xero OAuth cancelled or denied: {error_description}")
    from urllib.parse import urlencode
    params = urlencode({"xero_error": error_description})
    return redirect(f"{settings.LOGIN_URL}?{params}")
```

### 2. Fix existing exchange error path

Replace the existing `render()` call (lines ~119-122) for token exchange errors with the same redirect pattern:

```python
if "error" in result:
    from urllib.parse import urlencode
    params = urlencode({"xero_error": result["error"]})
    return redirect(f"{settings.LOGIN_URL}?{params}")
```

`settings.LOGIN_URL` is already defined as `FRONT_END_URL + "/login"`.

## Files to Change

- `apps/workflow/views/xero/xero_view.py` — two edits as above

## Verification

1. Start server, go to Xero login flow, click Cancel
2. Should redirect to the frontend login page (no 400/500 error page)
3. The login page URL should contain `?xero_error=TenantConsent+status+DENIED` (or similar)
4. No Django error page shown
