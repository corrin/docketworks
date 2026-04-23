# 0002 — Auth gate: single global gate with explicit allowlist

A blocking middleware gate rejects any request that is neither authenticated nor on the `AUTH_ANON_ALLOWLIST`; identity comes from cookies in all envs and, in DEV only, short-lived HS256 bearer tokens.

- **Status:** Accepted
- **Date:** 2025-10-30
- **PR(s):** Commit `f3b059f4` ("both authentication methods working") — predates GitHub PR workflow on this repo

## Context

PROD is internet-facing but almost all users are on LAN; existing cookie sessions work. DEV is short-lived with sanitised data. We want a single authentication rule across all environments — the *requirement* is identical everywhere — while allowing DEV to authenticate via short-lived JWT bearer tokens so test tooling doesn't need a login flow. Per-view decorators had been drifting: some views were unprotected by accident, others had env-conditional CSRF exemptions, and the public surface was implicit ("whatever doesn't have `@login_required`").

## Decision

Two layers. An **identity layer** (non-blocking) that reads either cookies (always) or, when `ALLOW_DEV_BEARER=true` and the host matches `DEV_HOST_PATTERNS`, a short-lived HS256 bearer signed with `DEV_JWT_SECRET` — on failure it does nothing, remaining anonymous. A **global gate** (blocking) that runs on every request: if not authenticated and the path is not in `AUTH_ANON_ALLOWLIST`, return `401 JSON` for `/api/**` or `302 /login` for everything else. The gate is authoritative; views do not rely on per-view decorators. PROD has `ALLOW_DEV_BEARER=false`, so bearer is ignored even if presented.

## Alternatives considered

- **Per-view decorators (`@login_required`):** status quo that was drifting; easy for a new view to ship unprotected.
- **Separate middleware stacks per environment:** satisfies the DEV bearer need but means PROD and DEV have measurably different auth *behaviour*, not just different identity sources — harder to reason about security invariants.
- **Shared bearer tokens across envs:** would require production-grade token issuance and rotation for what is only a dev-tooling convenience.

## Consequences

- **Positive:** one place to audit ("what is the authenticated surface?") — the allowlist. Adding a new public endpoint requires an explicit list entry. PROD can never accept a bearer because the flag controls whether the identity layer even tries.
- **Negative / costs:** the allowlist has to be maintained; forgetting to add `/healthz` or a new public asset path surfaces as a `302` redirect rather than a useful error.
- **Follow-ups:** if we ever move PROD to bearer, flip precedence inside the identity layer — the gate itself does not change.
