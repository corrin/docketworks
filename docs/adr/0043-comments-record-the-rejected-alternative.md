# 0043 — Comments record the rejected alternative

A comment answers: which obvious alternative did the author reject, and what fact rejected it?

## Rules

- Every comment tells the reader something the code cannot: the choice made, the obvious alternative rejected, and the fact that rejected it. The shape, from `apps/core/errors.py`: "The marker is metadata *about* the exception, deliberately not a wrapper type — wrapping would destroy the type the HTTP boundary needs to choose a status code."
- The same test governs docstring sentences beyond the contract summary. (Test docstrings have their own required shape — ADR 0025.)
- AI-authored rationale carries its model-family attribution until the owner ratifies it (ADR 0051); attribution records who supplied the judgement, not permission to ignore a rule.
- Sessions are this codebase's authors, and a rejected alternative that goes unrecorded is an alternative the next session will re-attempt — that is how v1's duplication began.
- A comment that fails the test is deleted, not reworded.

## Do not

- **Code-to-English narration** (`# Create estimate cost set` above code that creates the estimate cost set) — regenerable from the code; it carries nothing and goes stale the first time the code moves.
- **Review-feedback echoes** ("use bulk_create per review") — if the feedback identified a real constraint, record the constraint; the conversation is not a reason.
