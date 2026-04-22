# Route chatty dev loggers to files, keep console for real signal

## Context

The dev server console is being drowned by per-request INFO/WARNING lines during E2E-style runs (repeated login/logout, repeated `/me` calls), making it hard to spot the actual bug the user is currently debugging. None of these logs should be *silenced* — they're useful — they just shouldn't all hit stdout. The `LOGGING` config in `docketworks/settings.py` already has rotated file handlers (`auth_file`, `app_file`) for every noisy source; the noise is leaking to `console` only because three loggers either (a) aren't explicitly configured and so fall through to root, or (b) have `propagate: True` so their records bubble to root's `console` handler on top of going to their file handler.

Goal: every message still persists to a rotated file; the stdout copy is removed for the specific chatty loggers only. Nothing is silenced.

The user is actively debugging. After this change they can still watch the events live with `tail -f logs/auth.log` and `tail -f logs/application.log` in side terminals.

## File to change

- `docketworks/settings.py` — the `LOGGING["loggers"]` dict (lines 551–647)

## Changes

### 1. Stop `apps.accounts` leaking to console

Current (settings.py:637):

```python
"apps.accounts": {
    "handlers": ["auth_file"],
    "level": "INFO",
    "propagate": True,
},
```

Change `propagate` to `False`. This alone kills the stdout copy of:

- `[/ME] -> received request` — `apps/accounts/views/user_profile_view.py:35`
- `Fetching staff list with filters` — `apps/accounts/views/staff_views.py:84`
- `JWT LOGIN SUCCESS` — `apps/accounts/views/token_view.py:105`
- `Setting access token cookie` — `apps/accounts/views/token_view.py:157`

All still land in `logs/auth.log` unchanged (they inherit `apps.accounts`'s `auth_file` handler).

### 2. Route `apps.workflow.authentication` to `auth_file`

Currently unconfigured, so `JWT authentication failed: no valid token found (cookie '%s' present: %s)` at `apps/workflow/authentication.py:54` falls through to root → `console` + `app_file`. Add a dedicated entry:

```python
"apps.workflow.authentication": {
    "handlers": ["auth_file"],
    "level": "INFO",
    "propagate": False,
},
```

This keeps the record in `logs/auth.log` (alongside the `apps.accounts` auth logs, which is the natural home for it) and drops the stdout copy. Removes the E2E logout spam — which is the worst offender — from console.

### 3. Route `django.request` to `app_file`

Currently unconfigured, so `WARNING Unauthorized: /api/accounts/me/` falls through to root → `console` + `app_file`. Add:

```python
"django.request": {
    "handlers": ["app_file"],
    "level": "WARNING",
    "propagate": False,
},
```

401/403/404/5xx response logging stays in `logs/application.log`. **This does not silence 5xx errors** — Django emits them at ERROR, the `app_file` handler's level is DEBUG, so they persist to disk. Uncaught exception tracebacks raised inside views still hit root → console via other paths (`sys.excepthook` / runserver's traceback printer), so crashes remain visible at the terminal.

### 4. Route `django.server` to `access_file`

`django.server` is the runserver access-log logger — source of the `[22/Apr/2026 21:10:15] "GET /api/... HTTP/1.1" 200 42017` lines. Currently unconfigured, so every request hits console via root. The `access_file` handler and `access` formatter (bare `{message}`, which preserves the `[timestamp] "METHOD /path" status size` format runserver already embeds in the message) are already defined in settings. Add:

```python
"django.server": {
    "handlers": ["access_file"],
    "level": "INFO",
    "propagate": False,
},
```

Timeline reconstruction — which is how the user is actually debugging — happens via `tail -F logs/access.log` in a dedicated pane. Same format as before, just not on console. This logger only fires under `runserver` (nginx handles prod access logs), so this is dev-only.

## Out of scope

- **`workflow` and `apps.purchasing.views`** (both `propagate: True` today): not named in the spam sample, leave alone.
- No log levels are raised, no handlers dropped, no exceptions swallowed. Every record still reaches a rotated file.

## Does this break the current debug session?

The user is actively using these logs to diagnose a spontaneous logout between E2E tests. The reconstructed timeline was:

- `:00` Test 16 login success
- `:01-:06` Test 16 work (client/job creation, tab loads — all 200s)
- `:07` unexpected `POST /api/accounts/logout/ 200` (no test code called logout — frontend-initiated)
- `:07-:08` three `/me` → 401 (cookie gone), then one `/me` with a token that fails validation: "Given token not valid for any token type"
- `:09` Test 17 login success, `/me` 200
- `:09-:40` silence except `/build-id/` heartbeat
- `:39` Test 17 `locator.click('AppNavbar-create-job')` times out; screenshot shows `/login`

Walk the plan against it:

| Signal the user relied on | Source logger | After the change |
|---|---|---|
| `POST /api/accounts/logout/ 200` | `django.server` (runserver access log) | `logs/access.log` |
| `GET /api/accounts/me/ 401` x3 | `django.server` | `logs/access.log` |
| `POST /api/accounts/token/ 200` | `django.server` | `logs/access.log` |
| `GET /api/build-id/ 200` heartbeat | `django.server` | `logs/access.log` |
| 31s silence window (absence of access logs) | `django.server` | `logs/access.log` — silence still visible there |
| "Given token not valid for any token type" | `apps.workflow.authentication` INFO | `logs/auth.log` |
| `WARNING Unauthorized: /api/accounts/me/` | `django.request` | `logs/application.log` (redundant with the 401 on the access log anyway) |

Debugging workflow post-change: three `tail -F` panes — `access.log` (timeline), `auth.log` (auth detail), `application.log` (request-level warnings and anything else from root). The console is reserved for startup messages, tracebacks, scheduler/xero/mcp output, and anything unexpected.

## Verification

1. Apply the four edits to `docketworks/settings.py`.
2. Restart the dev server.
3. In three side terminals: `tail -F logs/access.log`, `tail -F logs/auth.log`, `tail -F logs/application.log`.
4. In the frontend, repeat the logged-out → login → logout cycle a few times to reproduce the E2E pattern.
5. On the dev-server console, confirm the following lines are **absent**:
   - `[22/Apr/2026 ...] "GET ..." 200` / any `django.server` access-log line
   - `JWT authentication failed: no valid token found`
   - `Unauthorized: /api/accounts/me/` (WARNING from `django.request`)
   - `[/ME] -> received request`
   - `Fetching staff list with filters`
   - `JWT LOGIN SUCCESS` / `Setting access token cookie`
6. Confirm they are **present** in the right files:
   - `logs/access.log`: the `[timestamp] "METHOD /path" status size` lines
   - `logs/auth.log`: `JWT authentication failed`, `[/ME]`, `Fetching staff list`, `JWT LOGIN SUCCESS`, `Setting access token cookie`
   - `logs/application.log`: `WARNING django.request Unauthorized: ...`
7. Trigger an uncaught error in a view and confirm the traceback still prints on console. Root logger is untouched, so any unhandled exception or code that logs outside the four reconfigured loggers still reaches stdout.
