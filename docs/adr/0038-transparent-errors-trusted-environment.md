# 0038 — Authenticated callers get the real exception; anonymous callers get fixed wording and no secrets

Authenticated staff receive the real failure; anonymous callers receive a fixed public contract. The origin is internet-reachable, so a request becomes trusted only after its app credential verifies.

## Rules

- Authenticated API error envelopes carry the real exception message plus `error_id`, so staff can diagnose a failure immediately and a screenshot cross-references the persisted `AppError`.
- Anonymous errors use fixed status-appropriate wording, never exception text. Unknown user, wrong password and inactive staff are externally indistinguishable; invalid token details remain in security logs without token material.
- Expected authentication refusals return a stable machine `code` and `error_id: null`, and do not create `AppError` rows (ADR 0019): they are security outcomes, not application faults. Edge nginx/fail2ban policy owns public rate enforcement for login and refresh.
- Secrets — keys, passwords, tokens, and credential-bearing upstream bodies — are never returned at either boundary. Transparency covers failure causes, not credential material.
