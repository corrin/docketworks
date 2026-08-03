# 0002 — Auth gate: single global gate with explicit allowlist

A blocking middleware gate rejects any request that is neither authenticated nor on `AUTH_ANON_ALLOWLIST`.

## Rules

- The gate runs on every request: not authenticated and path not in `AUTH_ANON_ALLOWLIST` → `401` JSON for `/api/**`, `302 /login` for everything else. The allowlist is the complete anonymous surface — adding a public endpoint is a deliberate list entry, and "what URLs accept anonymous traffic?" is answered by reading that one list.
- Identity comes from cookies in all environments. DEV only: when `ALLOW_DEV_BEARER=true` and the host matches `DEV_HOST_PATTERNS`, short-lived HS256 bearers signed with `DEV_JWT_SECRET` are also accepted, so test tooling never drives a login flow. PROD sets `ALLOW_DEV_BEARER=false`; a presented bearer is ignored because the identity layer never attempts it.
- A public path that was not allowlisted fails as a confusing `302` redirect — when anonymous traffic misbehaves, check the allowlist first.

## Do not

- **Per-view decorators (`@login_required`)** — the public surface becomes "whatever forgot the decorator", and new views ship unprotected.
