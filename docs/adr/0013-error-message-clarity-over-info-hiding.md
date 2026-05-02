# 0013 — Error message clarity wins over information hiding

Internal-tool error responses include the underlying exception message verbatim. Continue to include the persisted `AppError.id` as `details.error_id` for cross-reference.

## Problem

A code review on a report endpoint flagged that 500 responses returned `str(exc)` to the caller, which can leak internal details — stack-relevant strings, table names, integration error codes. The same pattern exists across every report endpoint. The standard public-API answer is to redact the message and return only an `error_id`. But this is not a public API: every caller is an authenticated employee of the deploying business.

## Decision

Return the underlying exception message in API error responses. Do not mask or generalise exception text for information-hiding reasons. Always include `details.error_id` so any response can be cross-referenced with structured logs and the `AppError` row.

## Why

Every caller is a logged-in employee, every action is recorded in `AppError` plus audit trails. The threat model is "employee who wants to keep their job" — not an anonymous internet attacker. Opaque messages cost real clarity for every support interaction (the employee has to look up the row by id before they can describe the failure to a colleague). Clarity is the dominant value when the audit trail covers the security side.

## Alternatives considered

- **Redact exception messages entirely, return only `error_id`.** Strongly defendable for any public-internet API. Rejected here: there is no untrusted caller; every triage starts with the employee pasting the error into chat, and an opaque message means a database lookup before the conversation can begin.
- **Redact only sensitive exception types (DB connection strings, credential errors).** Defendable as a hybrid. Rejected: the boundary between "sensitive" and "not" is fuzzy and tends to fail open over time; the audit trail covers the same threat without the complexity.

## Consequences

Error payloads are immediately useful in screenshots and bug reports. If docketworks is ever exposed to untrusted callers (a customer portal, a public read-only endpoint), revisit this ADR for that surface — this decision is scoped to the employee-authenticated API.
