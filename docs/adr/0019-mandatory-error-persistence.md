# 0019 — Every exception is persisted to AppError

Every `except` block in the codebase calls `persist_app_error(exc)` — errors live in postgres, not stdout — before re-raising via the dedup pattern in ADR 0001.

## Problem

Errors logged to stdout/stderr survive only as long as log retention. A scheduler error at 3am rotates out before anyone reads the logs; a failure that reproduced once last Tuesday is gone by Friday. There's no way to query "how often does this fail?" or "has this happened before?" because the log is unstructured text aging out of a file. Cross-referencing an error with the job, staff member, or PO it relates to means lining up timestamps by hand.

## Decision

Every `except` block calls `persist_app_error(exc)`, which stores the message, traceback, request context, and a UUID id in the `AppError` table. The handler then re-raises through the two-arm dedup pattern (ADR 0001) so the same failure isn't persisted twice as it travels up the stack. Continuation without re-raise is allowed only when business logic explicitly requires it.

## Why

Database-backed errors survive log rotation, are SQL-queryable, and join with everything else in the schema — a job's `AppError`s alongside its `JobEvent`s, a staff member's failures alongside their actions, a Xero sync failure alongside the invoice that triggered it. Support flips from "grep recent logs and hope" to "look up `AppError` by id." The error record is part of the system's permanent state, treated the same as any other domain row.

## Alternatives considered

- **Sentry / Datadog / equivalent SaaS.** The ubiquitous answer. Rejected: errors shaped by the vendor's data model rather than ours; no SQL-style join against `Job` / `Staff` / `JobEvent`; another vendor relationship to maintain. The functionality we'd actually use (persist, query, correlate) is what `AppError` already gives us in the same postgres instance the rest of the app talks to.
- **Structured JSON logs to ELK / Loki.** Defendable for high-throughput operational visibility. Rejected: gives query but not join — correlating a scheduler error with the job it ran against still means lining up timestamps, not following a foreign key.

## Consequences

Every code path through every `try`/`except` is observable forever — including paths in scheduler jobs and management commands that have no request context to lean on. Cost: `AppError` grows; eventual archival policy needed.
