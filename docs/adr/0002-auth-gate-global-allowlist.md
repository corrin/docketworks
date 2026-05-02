# 0002 — Auth gate: single global gate with explicit allowlist

A blocking middleware gate rejects any request that is neither authenticated nor on `AUTH_ANON_ALLOWLIST`. Identity comes from cookies in all envs and, in DEV only, short-lived HS256 bearer tokens.

## Problem

With per-view decorators (`@login_required`), the public surface is implicit — "whatever doesn't have the decorator is public" — and drifts. New views ship unprotected because someone forgot the decorator. There's no single place to answer "what URLs accept anonymous traffic?" without grepping every view in the codebase. DEV separately needs token-based auth so test tooling doesn't have to drive a login flow; PROD must not.

## Decision

Two layers. An **identity layer** (non-blocking) reads cookies always and, when `ALLOW_DEV_BEARER=true` and the host matches `DEV_HOST_PATTERNS`, an HS256 bearer signed with `DEV_JWT_SECRET`. A **global gate** (blocking) runs on every request: not authenticated and path not in `AUTH_ANON_ALLOWLIST` → `401 JSON` for `/api/**`, `302 /login` for everything else. The gate is authoritative; views do not rely on per-view decorators. PROD has `ALLOW_DEV_BEARER=false`, so bearer is ignored even if presented.

## Why

The authenticated surface lives in one file (the allowlist). Adding a public endpoint requires a deliberate list entry. PROD cannot accept a bearer because the identity layer doesn't even attempt it. DEV-only bearer means test tooling doesn't need a production-grade token-issuance system.

## Alternatives considered

- **Per-view decorators (`@login_required`).** The Django convention. Rejected: authenticated surface is implicit and drifts; auditing it means grepping every view; new views ship unprotected when the decorator is forgotten.

## Consequences

One place to audit the authenticated surface. Cost: forgetting to allowlist `/healthz` or a new public asset path surfaces as a confusing `302` redirect rather than a useful error.
