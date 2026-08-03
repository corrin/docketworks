# 0013 — Error message clarity wins over information hiding

API error responses include the underlying exception message verbatim, plus `details.error_id`.

## Rules

- Return the real exception message in error responses; never mask or generalise it for information-hiding reasons. Every caller is an authenticated employee of the deploying business, and every failure is already persisted and audited — ADR 0038 records the trust boundary and makes transparency the default across all surfaces.
- Always include `details.error_id` (the persisted `AppError` id) so any response — including a screenshot in a bug report — cross-references the structured logs and the database row.
- If any surface is ever exposed to untrusted callers (a customer portal, a public endpoint), revisit this for that surface before launch.
