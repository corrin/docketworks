# 0038 — Errors are transparent inside the authenticated trust boundary

Transparency is the staff default; authentication is the boundary that enables it.

## Rules

- Docketworks runs per client for a handful of known staff, but its origin is internet accessible so staff can work from home without a VPN. A request becomes trusted only after its app credential verifies.
- Authenticated API error envelopes carry the real exception message plus `error_id` (ADR 0013), so staff can diagnose a failure immediately.
- Anonymous errors use fixed wording. Unknown user, wrong password and inactive staff are externally indistinguishable; invalid token details remain in security logs without token material.
- Expected auth refusals do not create `AppError` rows (ADR 0019). Edge nginx/fail2ban policy owns public rate enforcement for login and refresh.
- Secrets — keys, passwords, tokens — are never echoed. Transparency covers failure causes, not credential material.
