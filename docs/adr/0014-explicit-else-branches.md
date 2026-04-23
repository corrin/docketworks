# 0014 — Explicit `else` branches on non-trivial `if`

`if` statements in non-trivial code paths should have an explicit `else` branch, even when the else body is a no-op or a comment. Makes the state machine legible and keeps "unhappy case first" honest.

- **Status:** Accepted
- **Date:** 2026-04-24
- **PR(s):** — (codebase convention, not a single PR)

## Context

CLAUDE.md already calls for handling unhappy cases first (`if <bad_case>: handle_error()` over `if <good_case>:`). In practice, code written this way often drops the `else` entirely once the bad case returns/raises, which hides the fact that *something* happens in the other branch — readers have to trace the fallthrough path manually. On reviews this keeps surfacing as "is this case handled? I can't tell."

The failure mode is worse when the "other branch" wasn't actually thought through: silent fallthrough looks identical to deliberate fallthrough. We'd rather force the author to name the path.

## Decision

For `if` statements with non-trivial control flow, include an explicit `else` branch. The `else` body can be:

- a comment noting where the case is handled — e.g. `else: pass  # handled by guard above` / `else: pass  # normal path continues below`
- real handling code for the alternate path
- `persist_app_error(exc); raise` when the branch represents an unexpected-but-possible state that the current code can't handle

Trivial guards with obvious fallthrough (`if not x: return`, single-line list/dict comprehensions, etc.) don't need the ceremony. The rule bites on branching logic that readers have to reason about.

## Alternatives considered

- **Leave it to taste:** what we had. Reviewers kept asking "is the else case handled?" on multiple reports. The ceremony is small and the clarity win is concrete.
- **Mandate explicit `else` on every `if`:** too noisy; early-return guards become ugly for no gain.

## Consequences

- **Positive:** state-machine-style code (most report builders, event replays, transition resolvers) reads as exhaustive. Forgotten branches become visible instead of invisible. Pairs cleanly with the unhappy-case-first rule.
- **Negative / costs:** slightly more vertical code; style reviewers have to judge what counts as "non-trivial." We accept that trade rather than legislate it further.
- **Follow-ups:** update CLAUDE.md so the rule is surfaced alongside the existing defensive-programming section (done in the same commit as this ADR).
