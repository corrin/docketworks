# 0019 — Every exception is persisted to AppError before re-raise

Every `except` block calls `persist_app_error(exc)` before re-raising. Errors live in the database, not just in stdout.

## Problem

Errors logged to stdout/stderr survive only as long as log retention. A failure that reproduced once last Tuesday is gone by the time the user reports it Friday; a scheduler error at 3am rotates out before anyone reads the logs. There's no way to query "how often does this fail?" or "has this happened before?" because the log is unstructured text aging out of a file. Cross-referencing an error with the job, staff member, or PO it relates to means grepping logs and timestamps.

## Decision

Every `except` block follows a two-arm pattern. If the caught exception is already an `AlreadyLoggedException` (ADR 0001), re-raise it unchanged — it has been persisted by an inner handler. Otherwise, call `persist_app_error(exc)`, wrap in `AlreadyLoggedException`, and re-raise. `persist_app_error` returns the `AppError` row so the UUID id can be carried forward into the wrapping exception and into API error responses (ADR 0013). The handler re-raises unless business logic explicitly requires continuation. Net effect: every distinct failure produces exactly one `AppError` row, regardless of how many `except` blocks the exception passed through.

## Why

Database-backed errors survive log rotation, are queryable, and join with everything else we care about — a job's `AppError`s alongside its `JobEvent`s, a staff member's failures alongside their actions. Support flips from "grep recent logs and hope" to "look up `AppError` by id". The error record is part of the system's permanent state, not transient operational noise on a disk somewhere.

## Alternatives considered

- **Sentry / Datadog / equivalent SaaS.** The ubiquitous answer. Rejected: another vendor relationship to maintain, another dashboard to teach support, errors shaped by the vendor's data model rather than ours, no SQL-style join against `Job` / `Staff` / `JobEvent`. The functionality we'd actually use (persist, query, correlate) is what `AppError` already gives us in our own postgres.
- **File-based error log outside log rotation.** Rejected: a file growing unbounded on disk has all the pathologies of a tiny database (locking, parsing, backup, rotation policy) without any of the tooling.

## Consequences

Every code path through every `try`/`except` is observable forever — including paths in scheduler jobs and management commands that have no request context to lean on. Cost: `AppError` grows; needs an eventual archival policy; every new `try`/`except` author must remember the two-arm pattern (ADR 0001) or risk double-persisting.
