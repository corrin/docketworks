# 0001 — Idempotent error persistence

`persist_app_error` marks the exception it persists and returns the existing row on any later call, so one failure is one `AppError` row no matter how many handlers catch it.

## Problem

Exceptions travel integration → service → view → scheduler. Every layer has its own `try/except` that calls `persist_app_error()`. Without deduplication the same failure gets persisted 4–5 times — one bug, four duplicate `AppError` rows. Scheduler jobs and management commands sit outside request middleware, so any "just centralise it in one outer handler" plan cannot reach them.

## Decision

`persist_app_error()` records the created `AppError` on the exception instance (a `__app_error__` marker) and, on any subsequent call for the same failure, returns that existing row instead of writing a new one. The dedup is idempotency in the function, not a discipline every handler has to follow. A handler is one arm:

```python
try:
    operation()
except Exception as exc:
    persist_app_error(exc)  # idempotent — one AppError row per failure
    raise
```

Lookup walks the `__cause__` chain, so a handler that *converts* the exception keeps the failure to one row as long as it chains the cause:

```python
except Job.DoesNotExist as exc:
    persist_app_error(exc)
    raise ValueError(f"Job {job_id} not found") from exc
```

The `from exc` is load-bearing: it is what links the converted exception back to the persisted one (pylint `W0707` enforces it repo-wide). Without the link the two are distinct objects and the second earns its own row.

The chain terminates at the HTTP boundary. The outermost handler chooses the response *status* from the exception's real type (`isinstance`, most-specific first) and reads the persisted id with `app_error_for(exc)` to include `error_id` in the body (ADR 0013). Service objects invoked by views always re-raise; they never shape responses. A service returns a failure value only for an *expected* business outcome, never for an unexpected exception.

## Why

Idempotency in the function means the guarantee holds no matter how many handlers a failure passes through — the caller cannot get it wrong by forgetting an arm. The exception keeps its real type all the way to the boundary, which is what lets the boundary map it to 404 / 409 / 412 / 503 rather than a blanket 500. It works identically in views, services, schedulers, and management commands, since it depends on nothing request-scoped.

## Alternatives considered

- **A marker wrapper (`AlreadyLoggedException`), the previous decision here.** Every handler was two-arm: re-raise the wrapper unchanged, else persist-wrap-raise. Rejected: wrapping conflated *metadata about* an exception ("already persisted") with the exception's *identity*, so carrying the marker destroyed the type the boundary needs to pick a status code. It also required every one of ~900 handlers to remember the pattern — and in practice most did not: the majority of call sites persisted and re-raised without wrapping, so the same failure double-logged anyway. Marking the exception instead of replacing it gives the same one-row guarantee without either cost.
- **Centralise persistence in middleware / a single outer handler.** Standard for request-scoped flows. Rejected: cannot reach scheduler jobs and management commands (no middleware), and the layer-local context that made the persisted message useful is gone.
- **Suppress duplicates at the DB layer via a content hash.** Common in heavy-throughput logging systems. Rejected: loses signal — which layer caught it, what message that layer produced — and does nothing for the scheduler-persistence gap.

## Consequences

One `AppError` row per real failure, guaranteed by `persist_app_error` rather than by every handler remembering a ritual; scheduler and management-command errors survive log rotation. `raise ... from exc` is mandatory on any handler that converts an exception, or the converted failure is persisted a second time. The exception's type reaches the boundary intact, so status-code mapping is `isinstance`-based, not name-string-based.
