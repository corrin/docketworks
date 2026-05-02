# 0001 — Exception deduplication via AlreadyLoggedException

Wrap once-persisted exceptions in `AlreadyLoggedException`; nested handlers re-raise unchanged instead of re-persisting.

## Problem

Exceptions travel integration → service → view → scheduler. Every layer has its own `try/except` that calls `persist_app_error()`. Without a marker, the same failure gets persisted 4–5 times — one bug, four duplicate `AppError` rows. Scheduler jobs sit outside request middleware, so any "just centralise it in one outer handler" plan cannot reach them.

## Decision

`AlreadyLoggedException` (in `apps/workflow/exceptions.py`) wraps the original exception plus the persisted `AppError.id`. Every handler is two-arm: re-raise `AlreadyLoggedException` unchanged; otherwise persist once, wrap, re-raise. `persist_app_error()` returns the `AppError` instance so callers can carry the id forward.

## Why

A marker exception is in-band — it works identically in views, services, schedulers, and management commands, so every handler in the codebase follows the same two-arm template. Reviewers and new handlers have one rule to remember. The id carries forward so an outer handler can correlate without re-querying.

## Alternatives considered

- **Centralise persistence in middleware / a single outer handler.** Standard for request-scoped flows. Rejected: cannot reach scheduler jobs (no middleware), and the layer-local context that made the persisted message useful is gone.
- **Suppress duplicates at the DB layer via a content hash.** Common in heavy-throughput logging systems. Rejected: loses signal — which layer caught it, what message that layer produced — and does nothing for the scheduler-persistence gap.

## Consequences

One `AppError` row per real failure; scheduler errors survive log rotation. Every new `try/except` must know the `AlreadyLoggedException` arm or risk double-persisting.
