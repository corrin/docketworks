# 0038 — Errors are transparent; rapid debugging outranks disclosure hygiene

Transparency is the default; masking a failure cause requires justification, not the reverse.

## Rules

- Docketworks runs per client, on client-controlled infrastructure, with a handful of known trusted staff users. Whoever is looking at the screen, the logs, or the `AppError` row should be able to diagnose the failure *now* — mask-by-default reflexes imported from public multi-tenant SaaS work against that.
- API error envelopes carry the real exception message verbatim at every status, including 500, plus `error_id` (ADR 0013).
- Auth rejections state their specific reason ("User is inactive.", the actual token-validation error) rather than a generic 401 string.
- Secrets — keys, passwords, tokens — are never echoed. Transparency covers failure causes, not credential material.
- If Docketworks ever becomes multi-tenant or internet-exposed to untrusted users, revisit this before that launch.
