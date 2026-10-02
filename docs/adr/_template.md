# NNNN — Title

The decision in one sentence. The knowledge index shows this line, so make it the rule itself, not a teaser.

## Rules

Imperative rules in clear, complete prose, written for the reader — usually an LLM session — who is mid-task in this codebase. Keep the concrete anchors: function names, status codes, commands, field lists. When a rule needs its reason to stick, attach the forcing fact as a clause ("— because the HTTP boundary needs the type to pick a status code"). Use an example only where the rule's shape is easier shown than described.

## Do not

- **A plausible alternative** — the constraint or tradeoff that led to this decision.

Include this section only when a competent engineer might reasonably consider the alternative
and the comparison helps explain the decision (ADR 0043). Otherwise omit it. Preserve useful
reasoning alongside the rule; extended deliberation remains in git history.
