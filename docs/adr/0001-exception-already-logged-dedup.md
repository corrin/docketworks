# 0001 — Exception deduplication via AlreadyLoggedException

Wrap once-persisted exceptions in `AlreadyLoggedException` so nested handlers pass through without creating duplicate `AppError` rows, and force scheduler jobs to participate so errors survive log rotation.

- **Status:** Accepted
- **Date:** 2025-11-04
- **PR(s):** [#195](https://github.com/corrin/docketworks/pull/195) — feat(admin-errors): dedup + group resolve (commit `aaa6c98b` added the plan; dedup/group work landed later in the admin-errors branch)

## Context

35 files call `persist_app_error()` and ~15–20 code paths have nested exception handlers that re-catch and re-persist the same exception, producing 4–5 `AppError` rows per actual failure. Meanwhile three scheduler modules don't call `persist_app_error` at all, so errors there vanish at log rotation. The same exception travels through integration → service → view → scheduler without a marker saying "already handled," so every layer tries to own it.

## Decision

Introduce `AlreadyLoggedException` in `apps/workflow/exceptions.py` that wraps an original exception plus the `AppError.id` it was persisted under. Every exception handler becomes a two-arm pattern: re-raise `AlreadyLoggedException` unchanged; catch anything else, persist once, wrap in `AlreadyLoggedException`, re-raise. `persist_app_error()` returns the `AppError` instance (previously returned `None`) so callers can carry the id forward. Roll out in phases: foundation (exception class + scheduler coverage) → integration layer → service layer → view layer → other entry points.

## Alternatives considered

- **Thread-local "already persisted" flag:** implicit state, harder to reason about across async/scheduler contexts, no way to carry the `AppError.id` back to a handler.
- **Centralise all `persist_app_error()` calls in a single outermost handler (e.g. middleware):** would miss scheduler jobs entirely (no request middleware) and would erase the layer-local logger context that's currently useful.
- **Suppress duplicates at write time via hash/dedup at the DB layer:** loses information (which layer saw the error, what message it generated) and doesn't fix the scheduler-persistence gap.

## Consequences

- **Positive:** one `AppError` row per real failure; scheduler errors survive log rotation; the re-raise/wrap pattern is the same in every layer, so reviewers and new handlers have one template.
- **Negative / costs:** ~100–120 files and ~200–300 handlers to update; every new `try/except` in the codebase now has to know about the `AlreadyLoggedException` arm or risk double-persisting.
- **Follow-ups:** the view layer and management commands phases are the largest fanout — confirm coverage with a grep for bare `persist_app_error` calls that aren't followed by a wrap-and-raise.
