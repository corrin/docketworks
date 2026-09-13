# 0002 — Auth gate: single global gate with explicit allowlist

A blocking middleware gate rejects any request that is neither authenticated nor on the anonymous allowlist, and the allowlist is the complete anonymous surface.

## Rules

- `LoginRequiredMiddleware` (`apps/core/middleware.py`) runs on every request. An anonymous request whose path is in `AUTH_ANON_ALLOWLIST_EXACT` or starts with an entry of `AUTH_ANON_ALLOWLIST_PREFIXES` passes; one under `/api/` passes to the ninja auth classes, which answer `401` in the standard envelope (ADR 0038); any other receives `401` JSON when it asked for JSON and otherwise a redirect to `FRONT_END_URL + /login` (`401` when `FRONT_END_URL` is unset, so a misconfiguration cannot loop). Adding a public endpoint is a deliberate entry in one of those two literals, and "what URLs accept anonymous traffic?" is answered by reading them.
- Identity is the cookie JWT (`CookieJWTAuth`, `apps/core/auth.py`), resolved by a separate non-blocking layer before the gate, in every environment.
- `PASSWORD_CHANGE_ALLOWED_PATHS` (`apps/core/auth.py`) is the same shape one layer up: while a session's password needs resetting, those are the only reachable authenticated paths.
- A public path that was not allowlisted fails as a confusing redirect — when anonymous traffic misbehaves, check the allowlist first.

## Do not

- **Per-view decorators (`@login_required`)** — the public surface becomes "whatever forgot the decorator", and new views ship unprotected.
- **Resolving allowlist entries from route names** — literal paths answer the public-surface question in one place; names spread across settings obscure it.
