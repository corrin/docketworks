# 0019 — Unexpected exceptions are persisted to AppError

Application faults live in postgres, not stdout; expected refusal paths are typed outcomes.

## Rules

- Every unexpected-exception handler calls `persist_app_error(exc, AppErrorContext(...))` — message, traceback, business context, UUID id into the `AppError` table — then re-raises. The context is the point of the handler: a row without the stock id, job id, or supplier it concerns cannot be joined back to anything.
- **One failure is one row.** `persist_app_error` is idempotent: it records the row on the exception instance as `__app_error__` and returns it on every later call, and the lookup walks `__cause__`, so a failure travelling through many handlers cannot double-persist. A handler that converts an exception must therefore chain it — `raise ValueError(...) from exc` — because without the chain the new exception earns a second row; ruff `B904` enforces it repo-wide.
- Expected domain refusals use the semantic categories in `apps.core.errors` and propagate unchanged to the single API boundary in `apps.core.envelope`. Domain services do not import Ninja or raise `HttpError`; routers do not catch a typed application error merely to wrap it. Generic `ValueError`, Django `ValidationError`, and model `DoesNotExist` are never mapped globally because each can also signal malformed provider data or an application fault.
- Missing credentials, invalid tokens, bad passwords and other expected authentication refusals are returned as typed outcomes and recorded through bounded security logging. Persisting one `AppError` per public rejection would turn internet noise into database-write amplification.
- Continuing without re-raising is allowed only when business logic explicitly requires it.
- A `try` needs a reason to exist: it converts an expected failure into a typed outcome, converts the failure's shape, or persists it with real business context. Expected catches carry the exception-gate's site-specific `deliberate-swallow` reason; absent one of those purposes, don't catch.

## Do not

- **Sentry/Datadog/ELK as the error store** — vendor-shaped records cannot be joined in SQL against `Job`, `Staff`, and `JobEvent`, which is how support actually correlates failures here.
- **Wrap the exception in a marker type (`AlreadyLoggedException`)** — wrapping destroys the type the HTTP boundary needs to choose a status code, and it demands a two-arm ritual from every handler.
- **Centralise persistence in middleware** — scheduler jobs and management commands never pass through it.
