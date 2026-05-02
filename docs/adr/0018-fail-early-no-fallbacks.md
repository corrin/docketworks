# 0018 — Fail early, handle unhappy cases first, no fallbacks

Validate inputs at the entry point, check the bad branch first, and never coerce missing or malformed values to defaults that mask the underlying problem.

## Problem

Code that validates the happy path and lets the bad case "fall through" surfaces failures three layers downstream from the actual bug. A missing config value silently defaults to `None`; a serializer silently returns `[]` for unparseable input; a view silently returns 200 with an empty payload. The user sees "the page is blank" instead of "`STAFF_ID` is unset." The root cause is that the bad case wasn't named at the top of the function, so the function silently kept going on with whatever shape it ended up with.

## Decision

In any non-trivial function, check the bad case first (`if <bad>: handle_error()`) before doing the work for the good case. Validate every required input at the call boundary; raise immediately on missing or malformed values rather than coercing them to defaults. No default values or fallbacks that paper over missing configuration or malformed rows. When the issue is data shape, repair the data (ADR 0015) — do not soften the consumer.

## Why

Failures surface at the layer with enough context to make them intelligible. A `KeyError: 'staff_id'` raised in the view that received the request is debuggable; the same value silently becoming `None`, threading through three services, and surfacing as "wage rate is 0" four screens later is not. Forcing the bad case to be written explicitly turns "is this case handled?" into a question with a visible answer rather than a guess. Pairs with ADR 0014 (explicit `else`): the `if` names the bad case, the `else` names the good case, neither is implicit.

## Alternatives considered

- **Tolerant readers — coerce missing or malformed input to a sensible default.** Defendable in form-handling layers and external-API consumers where the source genuinely produces noise we can't fix. Rejected here: docketworks's inputs come from forms we own and validate upfront, from Xero (a well-defined contract), and from our own DB (where bad rows are bugs to repair, not noise to absorb). Coercion in any of those layers hides a real defect.
- **Catch and continue at an outer boundary.** Standard for high-availability pipelines that must complete a partial run. Rejected: a multi-row sync that drops rows silently produces "synced 89 of 90 rows" with no record of which row failed; the sync looks fine, the missing row reappears next run as new work, and the underlying cause is never repaired.

## Consequences

Bugs surface at the layer that has the context to debug them, not three calls deeper. Crash-early code reads more pessimistically — every function leads with its bad cases — but is more honest about what it relies on. ADR 0014 (explicit `else`) and ADR 0015 (fix data, not fallback) are direct corollaries.
