# 0013 — Error message clarity wins over information hiding

Internal-tool error responses include the underlying exception message verbatim so the user on the other end can act on it; we rely on authenticated-session logging, not response redaction, to defend against escalation.

- **Status:** Accepted
- **Date:** 2026-04-24
- **PR(s):** #162 — Sales Pipeline Report v1

## Context

Docketworks is a single-tenant tool used exclusively by employees of the deploying business. A Copilot code review on the Sales Pipeline Report endpoint flagged that 500 responses return `str(exc)` to the caller, which can leak internal details. The same pattern exists across every existing report endpoint in `apps/accounting/views/`, so this is a codebase-wide question rather than a one-report decision.

The trade-off is: opaque messages ("An error occurred — error id X") protect against an attacker learning about the stack, but they also make it harder for the employee triaging the failure to tell their colleagues what went wrong without pulling the AppError row by id. There is no external user population to defend against.

## Decision

Return the underlying exception message in API error responses. Do not mask or generalise exception text for information-hiding reasons. Continue to include the persisted `AppError.id` as `details.error_id` so any response can be cross-referenced with structured logs and the DB row.

## Alternatives considered

- **Redact exception messages, return only `error_id`:** better for a public-internet app with untrusted callers, but costs clarity for every support interaction here — employees have to look up the `AppError` row before they can even describe the failure.
- **Redact only for specific sensitive exception types (DB connection strings, credential errors):** plausible, but the boundary is fuzzy and tends to fail open over time; not worth the complexity for a single-tenant employee tool.

## Consequences

- **Positive:** API error payloads are immediately useful in screenshots and bug reports; the employee reporting the bug can paste the full message. Triage starts with context already in hand.
- **Negative / costs:** An employee who wanted to attack the system could read the message to probe internals. Accepted risk: all requests are authenticated, all actions are logged to `AppError` + audit trails, and an employee using that path would be firing offence, not a technical exposure. The threat model is "employee who wants to keep their job," not "anonymous internet attacker."
- **Follow-ups:** If docketworks is ever exposed to untrusted callers (a customer portal, a public read-only endpoint, etc.), revisit this ADR for that surface — this decision is scoped to the employee-authenticated API.
