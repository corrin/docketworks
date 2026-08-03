# 0019 — Every exception is persisted to AppError

Every `except` block calls `persist_app_error(exc, AppErrorContext(...))` and re-raises; errors live in postgres, not stdout.

## Rules

- Every `except` block calls `persist_app_error(exc, AppErrorContext(...))` — message, traceback, business context, UUID id into the `AppError` table — then re-raises. The context is the point of the handler: a row without the stock id, job id, or supplier it concerns cannot be joined back to anything. Idempotency (ADR 0001) makes this safe at every layer of the same failure. Rows survive log rotation and join by foreign key to the job, staff member, or invoice involved; a 3am scheduler failure is still queryable on Friday.
- Continuing without re-raising is allowed only when business logic explicitly requires it.
- A `try` needs a reason to exist: it converts the failure's shape (into a domain error, or an HTTP status at the boundary), or it is the layer that can persist the failure with real business context. Absent both, don't catch — let it rise to a layer that qualifies.

## Do not

- **Sentry/Datadog/ELK as the error store** — vendor-shaped records cannot be joined in SQL against `Job`, `Staff`, and `JobEvent`, which is how support actually correlates failures here.
