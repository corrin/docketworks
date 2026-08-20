# 0043 — Comments record the rejected alternative

A comment answers: which obvious alternative did the author reject, and what *checked* fact rejected it?

## Rules

- Every comment tells the reader something the code cannot: the choice made, the obvious alternative rejected, and the fact that rejected it. The shape, from `apps/core/errors.py`: "The marker is metadata *about* the exception, deliberately not a wrapper type — wrapping would destroy the type the HTTP boundary needs to choose a status code."
- **The fact has to be one.** A rationale asserting something checkable — that no other implementation exists, that a call site is gated, that a value cannot be null, that a library would not fit, that a framework behaves a certain way — names the check that established it, or says plainly that it was not checked. The check is almost always a grep, a query, a test or a single run, and it is cheaper than the claim is durable. Two shapes, both acceptable: "the only other blob download is `open-blob.ts`, which defers its revoke" (checked, and the reader can repeat it), or "suspected rather than reproduced: the suite is chromium-only, and Chromium is the browser that wins this race" (unchecked, and saying so).
- An unchecked claim is more dangerous than a missing comment. A gap invites the next session to look; a confident sentence tells it not to bother, and the codebase then carries a belief that everything downstream is built on.
- The same test governs docstring sentences beyond the contract summary. (Test docstrings have their own required shape — ADR 0025.)
- AI-authored rationale carries its model-family attribution until the owner ratifies it (ADR 0051); attribution records who supplied the judgement, not permission to ignore a rule.
- Sessions are this codebase's authors, and a rejected alternative that goes unrecorded is an alternative the next session will re-attempt — that is how v1's duplication began.
- A comment that fails the test is deleted, not reworded.

## Do not

- **Code-to-English narration** (`# Create estimate cost set` above code that creates the estimate cost set) — regenerable from the code; it carries nothing and goes stale the first time the code moves.
- **A belief in the grammar of a fact** — "the pair is unique", "this is the only implementation", "the framework batches this" written flat, with nothing behind them. The reader cannot separate an assertion that was verified from one that was assumed, so the assumed one is believed. Check it, or mark it unchecked; the sentence costs the same either way.
- **Review-feedback echoes** ("use bulk_create per review") — if the feedback identified a real constraint, record the constraint; the conversation is not a reason.
