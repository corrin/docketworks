# 0014 — Explicit `else` branches on non-trivial `if`

`if` statements in non-trivial control flow include an explicit `else` branch, even when the `else` body is a comment or a no-op.

## Problem

CLAUDE.md already requires handling unhappy cases first (`if <bad_case>: handle_error()`). In practice, code written this way often drops the `else` once the bad case returns or raises. Readers then have to trace fallthrough manually to see what happens in the other branch. On reviews this surfaces as "is this case handled? I can't tell." Worse, when the other branch wasn't actually thought through, silent fallthrough looks identical to deliberate fallthrough — the bug and the design are visually indistinguishable.

## Decision

For `if` statements with non-trivial control flow, include an explicit `else`. The body can be:

- a comment naming where the case is handled — `else: pass  # handled by guard above` / `else: pass  # normal path continues below`;
- the alternate-path code itself;
- `persist_app_error(exc); raise` when the branch represents an unexpected-but-possible state the current code can't handle.

Trivial guards with obvious fallthrough (`if not x: return`, single-line comprehensions) don't need the ceremony. The rule bites on branching logic readers have to reason about.

## Why

Forcing an `else` makes the author name the path. Deliberate fallthrough becomes visible (a comment); accidental fallthrough becomes harder to write. Readers and reviewers can tell at a glance that the case has been considered. Pairs cleanly with unhappy-case-first: the `if` names the bad case, the `else` names the good case, neither is implicit.

## Alternatives considered

- **Mandate explicit `else` on every `if`.** Defendable — some style guides do this. Rejected: early-return guards become ugly for no clarity gain; trivial cases don't have the "is this handled?" ambiguity the rule exists to fix.

## Consequences

State-machine-style code (report builders, event replays, transition resolvers) reads as exhaustive. Cost: slightly more vertical code; reviewers must judge what counts as "non-trivial."
