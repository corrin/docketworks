# 0024 — Background work runs through Celery; tasks are idempotent and tenant-aware

Async work belongs in Celery tasks: idempotent, tenant-aware, write-side. Never in request handlers; never reached via `.delay().get()`.

## Problem

Without a task queue, request handlers absorb work that must complete before the response — third-party API pushes, slow renders, fan-out to many resources — and any external dependency's latency or retry behaviour ricochets through user-facing SLAs. Without rules for *how* a task is written, the queue itself becomes a landmine: tasks that double-execute on broker redelivery, tasks that pick the wrong tenant in a multi-instance deploy, tasks whose authors expect to read a return value the broker doesn't carry.

## Decision

Three rules apply to every async task:

1. **Background work runs through Celery, not the request handler.** Request handlers return ≤1s of CPU + I/O. Work whose duration is unbounded by the caller, work that calls third-party APIs that may slow, work that fans out, work that runs on a schedule — enqueued via Celery, response returns immediately. Nothing slow lives in the request path.

2. **Tasks are idempotent.** Brokers redeliver on worker crash and on configuration error. A task running twice must be safe — typically by reading current state and deciding whether the mutation is still needed, or by short-circuiting on a dedup key in the task body. "First delivery" is never an assumption.

3. **Tasks take their tenant as an explicit argument.** Workers serve one Django instance, but multi-tenant deploys run several; misconfiguration is invisible until tenant data crosses streams. Every tenant-aware task signature accepts the tenant id as a parameter — never read from `os.environ`, thread-locals, or singletons inside a task body.

Tasks are write-side. Results are written back to the database (or a notification surface) where the caller reads them. `.delay().get()` and synchronous result-fetching are forbidden.

## Why

A task queue is the architectural answer to "the request budget is too small for this work." Once the queue exists, the failure modes that come with brokers — redelivery, partial execution, worker-pool exhaustion — become design constraints every task author owns. Encoding idempotency and tenant-arg as rules at the queue boundary keeps the constraint visible at the call site, where reviewers see it. Forbidding `.get()` is the same principle from the other side: an async task is a *write* to the system, not a remote-procedure-call; a caller reading its result through the broker is using the wrong primitive.

## Alternatives considered

- **Allow task return values via a result backend.** Defendable for short-lived RPC-shaped flows where a caller blocks for a result; this is Celery's traditional shape. Rejected: encourages synchronous-feeling code on top of a queue, blurring the write-side discipline. Async work that needs to communicate a result writes it where readers expect to find it — the database — not back through the broker.
- **Bind tenant per-worker instead of per-task-arg.** Defendable in heavily isolated multi-tenant deploys that dedicate a worker pool per tenant. Rejected: makes the tenant boundary invisible at the call site, where reviewers need to see it; relies on operational configuration to remain correct rather than encoding the rule in the task signature.

## Consequences

A reviewer reads any new task and asks four questions: is it actually background-shaped, does double-delivery matter, is the tenant argument explicit, does anything read the result via `.get()`. The shape of every async surface — webhook handlers, scheduled emails, slow renders — collapses to the same template. Request handlers stay fast.
