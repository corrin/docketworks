# 0001 — Idempotent error persistence

`persist_app_error` marks the exception it persists and returns the existing row on any later call, so one failure is one `AppError` row no matter how many handlers catch it.

## Rules

- A handler is one arm — persist, then re-raise:

  ```python
  except Exception as exc:
      persist_app_error(exc, job_id=job.id)  # the context is why this handler exists
      raise
  ```

  Idempotency lives inside `persist_app_error` (it records the row on the exception instance as `__app_error__` and returns it on later calls), so a failure travelling through many layers cannot double-persist.

- A handler that converts an exception must chain it: `raise ValueError(...) from exc`. The dedup lookup walks `__cause__`, so the chain is what keeps the converted failure on the original row — without `from exc` the new exception earns a second row. Enforced repo-wide (W0707).

- The outermost HTTP handler picks the response status by `isinstance` on the exception's real type (most specific first — 404/409/412/503 rather than a blanket 500) and includes the persisted id in the body via `app_error_for(exc)` (ADR 0013).

- Services always re-raise; they never shape HTTP responses. A service returns a failure value only for an expected business outcome, never for an unexpected exception.

## Do not

- **Wrap the exception in a marker type (`AlreadyLoggedException`)** — wrapping destroys the type the HTTP boundary needs to choose a status code, and it demands a two-arm ritual from every handler that most of v1's ~900 handlers got wrong.
- **Centralise persistence in middleware** — scheduler jobs and management commands never pass through it.
