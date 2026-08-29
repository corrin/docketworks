"""Celery worker for the long-running Xero sync.

Lives in its own module (not in ``apps/xero/tasks.py``) so it can be
imported by both ``XeroSyncService`` (the dispatcher, which calls
``.delay()``) and re-exported from ``tasks.py`` without forming an import
cycle.

Under ``XERO_READONLY`` the whole run is suppressed — v1 expressed this as
the readonly provider's ``run_full_sync`` override; v2's worker calls the
sync engine directly, so the gate lives here. Blanket-blocked on purpose:
the full sync both pushes local stock to Xero and pulls tenant data into
the local DB, and neither belongs in a read-only test run.

Fable: progress goes out as django-eventstream publishes on
``settings.XERO_SYNC_CHANNEL`` (read by ``apps.xero.events.xero_sync_stream``),
not into cache buffers. The buffer scheme this replaces wrote message lists
nobody read — its readers were deleted as dead code — and re-reading a
growing list on every event made each publish O(run length).
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from apps.core.errors import persist_app_error
from apps.xero.client import XeroQuotaFloorReached, XeroSyncDisabled, XeroSyncLockLost
from apps.xero.sync_constants import SYNC_STATUS_KEY, release_sync_lock, require_sync_lock

# The lock's writer (this worker) and readers (gunicorn views) run in
# different processes, so sync state routes through the Redis-backed
# "shared" alias.
_sync_cache = caches["shared"]

logger = logging.getLogger(__name__)


def _publish(payload: dict[str, object]) -> None:
    """Publish one progress event to the sync stream's channel."""
    # Call-time import: django_eventstream reads Django settings at import.
    from django_eventstream import send_event  # noqa: PLC0415

    send_event(settings.XERO_SYNC_CHANNEL, "message", payload)


def _publish_sync_failure(
    *,
    task_id: str,
    message: str,
    sync_status: str,
    app_error_id: str | None = None,
) -> None:
    # An abort is operational, not an error: the page derives its terminal
    # toast from sync_status, and an aborted run must not read back as a
    # failed one.
    severity = "warning" if sync_status == "aborted" else "error"
    error_payload: dict[str, object] = {
        "datetime": timezone.now().isoformat(),
        "entity": "sync",
        "severity": severity,
        "message": message,
        "progress": None,
        "task_id": task_id,
    }
    if app_error_id:
        error_payload["error_id"] = app_error_id
    _publish(error_payload)
    _publish(
        {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "info",
            "message": "Sync stream ended",
            "sync_status": sync_status,
            "progress": None,
            "task_id": task_id,
        }
    )


def _publish_abort_marker(task_id: str, message: str) -> None:
    _publish(
        {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "warning",
            "message": message,
            "progress": None,
            "task_id": task_id,
            "sync_status": "aborted",
        }
    )


@shared_task(name="apps.xero.tasks.xero_sync_task")
def xero_sync_task(
    task_id: str,
) -> None:
    """Execute one Xero sync run end-to-end.

    Dispatched by ``XeroSyncService.start_sync()`` after it has acquired the
    Redis lock. django_celery_results records the real outcome of each run
    (SUCCESS, FAILURE-with-traceback, REVOKED on worker crash).

    The dispatcher holds the SYNC_STATUS_KEY lock (value = this task id)
    until the finally block releases it — and the release is owner-checked,
    so a redelivered or expired-lock task cannot free a newer run's lock.
    Tenant is implicit (single-tenant per Django instance —
    CompanyDefaults.get_solo()), consistent with the rest of the Xero code
    path.
    """
    # Call-time import: the sync engine pulls in the whole transform tree.
    from apps.xero.sync import ENTITY_CONFIGS, synchronise_xero_data  # noqa: PLC0415

    # Redelivery guard: acks_late + a Redis visibility timeout shorter than a
    # deep sync means the broker CAN redeliver a live run's message. The lock
    # value is the owning task id; a delivery that no longer owns the lock
    # must not run a second concurrent sync (or publish over the live run).
    if _sync_cache.get(SYNC_STATUS_KEY) != task_id:
        logger.warning("Xero sync task %s skipped: lock not held (redelivery or expiry)", task_id)
        return

    try:
        if settings.XERO_READONLY:
            # v1 parity: XeroReadOnlyProvider.run_full_sync skipped the whole
            # run with this message.
            _publish_abort_marker(task_id, "Sync skipped: XERO_READONLY is set")
            logger.info("Xero sync task %s skipped: XERO_READONLY", task_id)
            return

        processed = 0
        # +2: the pay_items pseudo-entity the orchestrator emits first, and
        # the stock_local_to_xero push that also emits a Completed event.
        total_entities = len(ENTITY_CONFIGS) + 2

        for message in synchronise_xero_data():
            enriched: dict[str, object] = dict(message)
            enriched["task_id"] = task_id

            if "progress" in enriched and enriched["progress"] is not None:
                enriched["entity_progress"] = enriched.pop("progress")

            # Indexed, not .get(): every event declares an entity, so a
            # missing one is a producer defect and must not read as "sync".
            entity = message["entity"]
            if entity != "sync" and enriched.get("status") == "Completed":
                processed += 1

            overall = processed / total_entities if total_entities > 0 else 0.0
            enriched["overall_progress"] = round(overall, 3)

            if "recordsUpdated" in enriched:
                enriched["records_updated"] = enriched["recordsUpdated"]

            _publish(enriched)
            # Renew the lock's lease on every progress event, so it means
            # "four hours since this run last made progress" rather than
            # "four hours since it started". A deep sync (5000 days back on a
            # first run) outlives a fixed lease and would drop its lock while
            # still writing, letting the next hourly dispatch start a second
            # concurrent sync. Rejected alternatives: a longer fixed timeout
            # (still finite, and it lengthens every stuck-run outage by the
            # same amount) and a separate heartbeat task (a second liveness
            # mechanism, when the progress stream already is one).
            require_sync_lock(task_id)

        _publish(
            {
                "datetime": timezone.now().isoformat(),
                "entity": "sync",
                "severity": "info",
                "message": "Sync stream ended",
                "overall_progress": 1.0,
                "entity_progress": 1.0,
                "sync_status": "success",
                "task_id": task_id,
            }
        )
        logger.info("Completed Xero sync task %s", task_id)

    # deliberate-swallow: the gate is off, which is configuration, not a
    # defect — no AppError, no re-raise, an "aborted" marker for the stream.
    # The engine owns the decision and this branch only reports it; the
    # worker deliberately does not read CompanyDefaults for itself, which is
    # what made the gate a four-way policy.
    except XeroSyncDisabled as exc:
        logger.info("Xero sync task %s skipped: %s", task_id, exc)
        _publish_abort_marker(task_id, f"Sync skipped: {exc}")

    # deliberate-swallow: operational abort, not a defect. Do NOT
    # persist_app_error (24+ rows/day at the floor would be noise), do not
    # re-raise (the task ran and decided to abort cleanly — TaskResult
    # SUCCESS is correct). The "aborted" marker is what distinguishes this
    # from a clean run for the UI, scheduler and monitoring.
    # XeroSyncLockLost is the same shape: the run lost its lock to a
    # successor, so stopping IS the correct outcome and the successor is
    # already doing the work (the owner-checked release in the finally leaves
    # the successor's lock alone). One handler, because the two produce one
    # outcome — an aborted run.
    except (XeroQuotaFloorReached, XeroSyncLockLost) as exc:
        logger.warning("Xero sync %s aborted: %s", task_id, exc)
        _publish_sync_failure(
            task_id=task_id,
            message=f"Sync aborted: {exc}",
            sync_status="aborted",
        )

    except Exception as exc:
        err = persist_app_error(exc)
        _publish_sync_failure(
            task_id=task_id,
            message=f"Error during sync: {exc}",
            sync_status="error",
            app_error_id=str(err.id),
        )
        raise

    finally:
        release_sync_lock(task_id)
