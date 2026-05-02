# 0016 — Ambiguous names trigger rename, not grandfathering

When a name is found to carry more than one meaning, rearchitect and rename every occurrence in a dedicated PR. No baseline, no allowlist, no "we'll fix it when we touch the file next."

## Problem

Names in this codebase have quietly drifted into multi-meaning. `wage_rate` could be cash or loaded; `unit_cost` could be either; the `Wage` column header doesn't say which it shows. Two calls that look identical at the source level return different numbers depending on which entry point a caller used. The bug surfaces as "wrong number on the screen" — the actual root cause is that the name doesn't tell the caller which value it returns.

## Decision

When an ambiguous name is identified, rename everything: model field → migration → serializer → API field → frontend type → grid column → every consumer, end-to-end, in a dedicated rename PR. No grandfathering, no legacy allowlist, no waiting. No fallbacks to the legacy name (no `getattr(obj, 'new_name', obj.old_name)`, no serializer accepting both, no DB column kept "for safety," no aliased re-exports). The rename PR removes the old name in the same commit that adds the new one.

## Why

Calling the wrong meaning becomes structurally impossible: it requires consciously typing the wrong word. Code review on these areas becomes mechanical — the meaning is in the name, or the reviewer flags it. Allowlists and gradual migrations preserve the ambiguity they exist to eliminate; every shim is a small cost paid forever by every reader. This is ADR 0015 (fix-data-not-fallback) applied to identifiers and ADR 0017 (zero backwards compatibility) applied to a naming change — same principle in three forms.

## Alternatives considered

- **Legacy allowlist / baseline (ESLint-baseline style).** Strongly defendable: ships the rule cheaply, lets the team land it incrementally. Rejected: normalises the ambiguity the rule exists to fix; the baseline shrinks too slowly to be honest.
- **Runtime parameter — `get_costs(loaded=True)`.** Defendable as a typed flag instead of a rename. Rejected: pushes disambiguation onto every call site; one forgotten kwarg and the bug returns silently.
- **Type aliases (`WageRateCash = Decimal`) or comments.** Defendable in a type-system-heavy codebase. Rejected: unenforceable at boundary crossings (ORM ↔ JSON ↔ grid), invisible at the call site.

## Consequences

Ambiguous calls become impossible to write accidentally. Cost: rename PRs sweep wide and carry migration risk; sequence them deliberately to limit conflicts on in-flight branches.
