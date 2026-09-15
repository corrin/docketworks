# 0024 — Background work runs through Celery; tasks are idempotent and write-side

Work that is slow, fans out, runs on a schedule or calls a third party is a Celery task, and every task can be delivered twice without harm.

## Rules

- Work that is slow, fans out, runs on a schedule, or calls third-party APIs runs as a Celery task. Request handlers stay under ~1 second of CPU + I/O and return immediately after enqueueing — an external dependency's latency must not ricochet through user-facing response times.
- Every task is idempotent — brokers redeliver on worker crash and on configuration error, so "first delivery" is never an assumption. Read current state and decide whether the mutation is still needed, or short-circuit on a dedup key in the task body.
- An install is single-tenant (ADR 0012): its one Xero tenant is read from the install's own configuration, never from `os.environ` or a thread-local. A task handling an inbound vendor message — the Xero webhook handler — takes the tenant id the message named as an explicit argument, so the check against the install's tenant is visible at the call site.
- Tasks are write-side: results are written to the database (or a notification surface) where callers read them.

## Do not

- **`.delay().get()` or any synchronous result-fetch through the broker** — a task is a write to the system, not an RPC; a caller blocking on the broker is using the wrong primitive.
