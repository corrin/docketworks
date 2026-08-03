# 0024 — Background work runs through Celery; tasks are idempotent and tenant-aware

Async work is a Celery task: idempotent, tenant-as-argument, write-side.

## Rules

- Work that is slow, fans out, runs on a schedule, or calls third-party APIs runs as a Celery task. Request handlers stay under ~1 second of CPU + I/O and return immediately after enqueueing — an external dependency's latency must not ricochet through user-facing response times.
- Every task is idempotent — brokers redeliver on worker crash and on configuration error, so "first delivery" is never an assumption. Read current state and decide whether the mutation is still needed, or short-circuit on a dedup key in the task body.
- Every tenant-aware task takes the tenant id as an explicit argument — never from `os.environ`, thread-locals, or singletons — so the tenant boundary is visible at the call site where reviewers can see it, not buried in worker configuration.
- Tasks are write-side: results are written to the database (or a notification surface) where callers read them.

## Do not

- **`.delay().get()` or any synchronous result-fetch through the broker** — a task is a write to the system, not an RPC; a caller blocking on the broker is using the wrong primitive.
