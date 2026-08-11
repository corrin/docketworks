# 0019 — Unexpected exceptions are persisted to AppError

Application faults live in postgres, not stdout; expected refusal paths are typed outcomes.

## Rules

- Every unexpected-exception handler calls `persist_app_error(exc, AppErrorContext(...))` — message, traceback, business context, UUID id into the `AppError` table — then re-raises. The context is the point of the handler: a row without the stock id, job id, or supplier it concerns cannot be joined back to anything. Idempotency (ADR 0001) makes this safe at every layer of the same failure.
- Missing credentials, invalid tokens, bad passwords and other expected authentication refusals are returned as typed outcomes and recorded through bounded security logging. Persisting one `AppError` per public rejection would turn internet noise into database-write amplification.
- Continuing without re-raising is allowed only when business logic explicitly requires it.
- A `try` needs a reason to exist: it converts an expected failure into a typed outcome, converts the failure's shape, or persists it with real business context. Expected catches carry the exception-gate's site-specific `deliberate-swallow` reason; absent one of those purposes, don't catch.

## Do not

- **Sentry/Datadog/ELK as the error store** — vendor-shaped records cannot be joined in SQL against `Job`, `Staff`, and `JobEvent`, which is how support actually correlates failures here.
