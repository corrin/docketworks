# 0047 — The application is served over ASGI, and data versions are pushed over SSE

Gunicorn runs the ASGI application under uvicorn workers, and every change to a data-version source model is pushed to connected tabs over server-sent events; polling is the fallback for a tab whose stream is down, never the mechanism.

## Rules

**Serve `config.asgi:application`.** The systemd unit runs
`gunicorn -k uvicorn_worker.UvicornWorker --workers 4 --timeout 180`, bound to
the instance's unix socket, rendered from
`scripts/server/templates/gunicorn-instance.service.template`. The unit name
stays `gunicorn-<instance>`: deploy, rollback and the sudoers rules address the
service by that name, so renaming it silently breaks rollback rather than
failing loudly. Editing the template changes the server-setup hash that
`scripts/server/deploy.sh` compares, so the next deploy re-converges every host
— that is the mechanism working, not a fault.

**Know what the ASGI move does and does not buy.** Django's ASGI handler wraps
each request in its own `ThreadSensitiveContext` (`django/core/handlers/
asgi.py`), so every in-flight request gets its own thread-sensitive executor
and sync views run concurrently: worker count does not bound sync-view
concurrency. What does bound it is database connections — `CONN_MAX_AGE` is 0,
so a request holds one while it queries — and process memory. What the ASGI
move buys is that a stream costs an event-loop task rather than a request slot:
a worker holds many open streams at once, and the arbiter's `--timeout`
watchdog never sees a worker that looks hung mid-request. Nothing here has
measured the load, so sizing `--workers` against observed connection and memory
use is an operations question, not a number this ADR sets.

**Version bumps come from signals over a source-model registry, never from
publish calls at write sites.** `DATA_VERSION_SOURCE_MODELS` in
`apps/operations/push.py` maps each dataset in the `/api/data-versions/`
document to the models that feed it, mirroring `DATASET_VERSION_PROVIDERS`, and
`post_save`/`post_delete` on those models are what schedule a publish. Add a
dataset to one registry and you add it to the other; `apps/operations/tests/
test_push.py` fails when they disagree, because a dataset with a provider and
no source models answers the poll correctly and silently never pushes.

**Publish after the transaction commits, once per transaction, and never let
the publish break the commit's other callbacks.** `transaction.on_commit(...,
robust=True)` is registered at most once per transaction — a bulk sync commits
thousands of rows, and each would otherwise queue a callback whose whole body
is a Redis round trip. A publish failure persists an `AppError` and is logged
(ADR 0038) rather than propagating, because Django abandons every later
on-commit callback once one raises, and the data has already committed by then.

**A write burst costs one leading publish and one trailing publish.**
`schedule_data_versions_publish` takes a one-second `cache.add` lock on the
shared Redis cache: the winner publishes immediately, which is what makes a
single edit feel instant, and queues
`apps.operations.tasks.publish_data_versions_task` with `countdown=1`, which is
what stops the last write of a burst being the one that never arrives. The task
recomputes versions at run time and is idempotent by construction, so celery's
at-least-once delivery is correct rather than tolerated (ADR 0024). It carries
no retry: the next publish, or the client's own poll, covers a lost trailing
edge, and a retry queue for an idempotent freshness ping buys nothing.

**Queryset writes announce themselves through `JobQuerySet.untracked_update`.**
It is the one Job UPDATE path — `update()` delegates to it after its
tracked-field guard, and `touch_updated_at()` is a named case of it — and it
calls `apps.core.data_events.notify_data_changed()`, the observer seam that
lets `apps.job` announce a write without importing `apps.operations` (the layer
contract forbids that direction). Announcing on a write that moves no version
is free, because the publisher coalesces and its payload is idempotent, while
missing one is a permanently stale tab with no error anywhere. The writers that
still bypass both signals and timestamps are inventoried in `push.py`'s module
docstring; each is a gap in what a dataset version means, not a delivery gap,
so closing one belongs at the timestamp, not at the push layer.

**The stream is django-eventstream, mounted as a plain view beside its polling
sibling.** `GET /api/data-versions/stream/` (`apps/operations/events.py`) sits
in `config/urls.py` next to `/api/data-versions/`, outside ninja and the
OpenAPI schema for the same reason the Xero OAuth views are — an endless
response is not an operation the generated axios client can call. It
authenticates the cookie JWT directly, because `EventSource`-style consumers
send a same-origin cookie and cannot set an Authorization header. It sets
`Content-Encoding: identity` so `GZipMiddleware` leaves it alone; compressing a
stream buffers events into compression blocks. The one event is `data_versions`
and its payload is exactly the document the poll serves, so a consumer needs no
second parser and no second shape.

**Cross-process fan-out is raw Redis pub/sub, on an instance-namespaced
channel.** `EVENTSTREAM_REDIS` is built from `REDIS_URL` with redis-py's
`parse_url`, and settings reject a URL whose scheme injects a
`connection_class` at startup rather than at the first published event, because
the library builds both a sync and an async client from that one dict.
`DATA_VERSIONS_CHANNEL` includes the database name: Redis pub/sub is
server-wide rather than scoped to a database index, and instances share one
redis-server, so an unnamespaced channel delivers one instance's events to
another. The test settings `del EVENTSTREAM_REDIS`, because the library selects
its multiprocess listener on that setting's mere presence.

**No storage backend, so no event ids and no replay.** The contract is
latest-state-wins: every push carries the complete current document, so history
has no value and a resuming client only needs the present. A reconnecting tab
closes its own gap by fetching the versions once on the library's `stream-open`
event and running a reconcile pass.

**On the frontend the stream is primary and the poll is a disconnect-only
fallback.** `frontend/src/api/data-versions-stream.ts` wraps the generated
hey-api SSE client, living in `src/api` because that is where generated-client
imports belong (ADR 0021). `useKanbanReconciliation` writes each pushed
document into the query cache with `setQueryData` and then runs `reconcile()`
behind a 300ms trailing debounce; the 30-second `refetchInterval` is off while
the stream is healthy, so exactly one trigger owns each pass. The query's own
observer tells write origins apart rather than standing down wholesale: it
defers only while the cached document is the one the stream last wrote, and
reconciles an HTTP-originated write — a focus refetch, the connect catch-up —
even on a healthy stream, because storage-free pub/sub drops a publication
rather than queueing it and the connection survives that drop. For the same
reason the connect catch-up restores a push that arrived while its read was
open, rather than leaving the older document that read just wrote.
Disconnection is
reported once per streak, not once per retry. A malformed frame is dropped
without touching stream health — a document the shape guard rejects means the
server changed the document, which fails the polling sibling identically, so it
is no evidence this connection is the broken part — and a stream the server
ends cleanly reopens after three seconds without a report.

**Watch the Redis listener, not just the streams.** django-eventstream 5.3.4
schedules `start_redis_listener()` once per server process with
`loop.create_task()` and never restarts it: it is an asyncio task on the
worker's event loop, not a thread, and it ends when its Redis connection drops.
The failure is silent from a client's side — streams stay open, keep-alives
keep arriving, and nothing is ever pushed — so `streamHealthy` stays true and
the client's disconnect fallback never arms. What still reconciles is an
HTTP-originated write to the versions query: `useKanbanReconciliation` runs a
pass for any cache write the stream did not make, so a focus refetch or a
drag/move release closes the gap on a board someone is using. A board nobody
touches stays stale, so treat "streams connected and no events during known
writes" as an incident and restart the service.

**`CONN_MAX_AGE` stays 0.** Persistent connections under many concurrent
streams is a post-cutover tuning question, and raising it now would multiply
open Postgres connections by a number nothing has measured.

**`django_eventstream` in `INSTALLED_APPS` brings its migration.** Cutover
migrates an empty database before restoring, so production takes it in the
normal order; a developer database needs `manage.py migrate` after picking this
up.

## Do not

- **Put a server-side poll loop behind the SSE endpoint** — a stream fed by the
  server polling its own database is a poll with a longer connection, not push,
  and it reintroduces exactly the latency the push path exists to remove (user
  decision, 2026-08-13).
- **Add channels or channels-redis** — django-eventstream 5.x runs
  channels-free under ASGI, so the ASGI application is the only runtime it
  needs.
- **Introduce Pushpin or another GRIP proxy** — it is a second network daemon to
  install, monitor and roll back on every host, for fan-out that Redis pub/sub
  already does with a dependency the stack already carries.
- **Enable eventstream's storage backend or Last-Event-ID replay** — every push
  carries the whole current document, so a replayed history tells a client
  nothing its next frame does not, and it buys a table and a retention question.
- **Call a publish helper from each write site instead of the signals** — the
  bumps have to come from every writer, including celery tasks, merges and
  management commands, and a forgotten call site is a permanently stale tab
  with nothing logged anywhere.
- **Serve the stream through a ninja operation** — it lands in the OpenAPI
  schema, and the API-boundary gate then demands it be called through generated
  axios code that cannot consume an endless response.
