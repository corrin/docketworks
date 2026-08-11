# 0013 — Error clarity follows the authentication boundary

Authenticated staff receive actionable failures; anonymous callers receive a safe contract.

## Rules

- After authentication succeeds, return the real exception message plus `error_id`; staff operate the system and need a screenshot to cross-reference the persisted failure immediately.
- Before authentication succeeds, return fixed status-appropriate wording rather than exception text. Docketworks is internet accessible for WFH, so the public origin is not a trusted boundary even though almost every successful caller is staff.
- Expected authentication refusals return a stable machine `code` and `error_id: null`; they are security outcomes rather than application faults.
- Secrets — keys, passwords, tokens, and credential-bearing upstream bodies — are never returned at either boundary.
