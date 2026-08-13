"""Server-push half of the data-version contract.

``/api/data-versions/`` answers "has anything changed?" only when a tab asks.
The same document is pushed over SSE the moment it changes, so a tab left open
reconciles immediately; the poll stays as the reconnect and backgrounded-tab
path.

Signals are the mechanism because a version bump has to come from EVERY
writer, including the ones no service function knows about: a Company rename
inside a merge, a CostLine cascade, a management command. Calling a publish
helper at each write site is the arrangement that decays — one forgotten call
is a permanently stale tab with no error anywhere. Hanging off ``post_save``
is safe for Job specifically because ``JobQuerySet.update()`` already rejects
tracked fields (models/job.py), so a tracked Job write cannot dodge ``save()``.

A publish failure is persisted as an AppError and logged, but is not allowed
to propagate out of the commit hook: Django runs on-commit callbacks in
registration order and a raising callback abandons every later one, so a Redis
blip would take out unrelated side effects of a transaction that has ALREADY
committed. ``robust=True`` plus ``persist_app_error`` keeps the failure loud
(ADR 0038) without that blast radius.

Writes this substrate does NOT see, all of them queryset ``.update()`` on a
source model, which skips both ``save()`` and the signals:

- ``apps/quoting/services/stock_parser.py`` (parser attempt/result columns)
- ``apps/purchasing/services/stock_service.py`` (soft delete, ``is_active``)
- ``apps/job/services/job_service.py`` (``Stock.quantity`` F() adjustments)
- ``apps/company/services/company_merge_service.py`` and
  ``person_merge_service.py`` (reassigning PhoneCallRecords to the survivor)
- ``apps/company/services/person_service.py`` (deactivating CompanyPersonLinks)

None of them moves the ``updated_at`` the matching provider reads, so none is
visible to the ``/api/data-versions/`` poll either: they are a gap in what a
dataset version MEANS, not a gap in delivery, and closing them at the push
layer alone would make push and poll disagree. Job is the exception and is
already closed — ``JobQuerySet.untracked_update()`` announces itself through
``apps.core.data_events``, because Job writes DO move ``updated_at``
deliberately.
"""

import logging
from itertools import chain

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.db.models import Model
from django.db.models.signals import post_delete, post_save
from django_eventstream import send_event

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.core.data_events import register_publisher
from apps.core.errors import AppErrorContext, persist_app_error
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.job.models import Job
from apps.operations.api import current_data_versions
from apps.purchasing.models import Stock

logger = logging.getLogger(__name__)

#: SSE event name the SPA listens for. The payload is the same JSON object
#: ``data_versions_retrieve`` serves.
DATA_VERSIONS_EVENT = "data_versions"

#: Which models feed which dataset version, mirroring
#: ``DATASET_VERSION_PROVIDERS``. Nothing at runtime checks the two against
#: each other; ``test_push.py`` does, because a dataset with a provider and no
#: source models answers the poll correctly and silently never pushes.
DATA_VERSION_SOURCE_MODELS: dict[str, tuple[type[Model], ...]] = {
    "stock": (Stock,),
    "kanban": (Job,),
    "kanban_related": (Company, CompanyPersonLink, Person, Staff),
    "crm_calls": (
        PhoneCallRecord,
        PhoneCallRecording,
        Company,
        CompanyPersonLink,
        Person,
        Job,
    ),
}

PUBLISH_LOCK_KEY = "data-versions-publish"

#: Width of the coalescing window, in seconds. A save storm — a Xero sync, a
#: bulk import, a job with forty cost lines — would otherwise publish per row,
#: and the client's answer to every one of those events is the same refetch.
PUBLISH_COALESCE_SECONDS = 1

_SIGNAL_DISPATCH_UID = "operations.push.data_versions"


def publish_data_versions_now() -> None:
    """Compute fresh versions and push them to every connected stream."""
    send_event(settings.DATA_VERSIONS_CHANNEL, DATA_VERSIONS_EVENT, current_data_versions())


def publish_trailing_data_versions() -> None:
    """Release the coalescing lease, then publish the settled versions.

    The delete comes FIRST, and the order is the point. A commit landing
    between it and the read below is already in the payload this publish sends;
    a commit landing after the read finds no lease, takes a fresh one and
    publishes leading. Nothing can be suppressed by a lease that outlives the
    payload it was coalescing into.

    Matching the lease TTL to the task's countdown was the alternative and it
    does not hold: the lease is set on a web host and the countdown elapses on
    a celery host, so any clock skew — or an eagerly scheduled task — lets the
    task read while the lease still stands, and that read's window silently
    swallows every write it did not see.
    """
    caches["shared"].delete(PUBLISH_LOCK_KEY)
    publish_data_versions_now()


def schedule_data_versions_publish() -> None:
    """Publish immediately, and once more when the write burst settles.

    ``cache.add`` on the shared (Redis) cache is the deduplication: it
    succeeds for exactly one caller per window across every worker process and
    celery worker. So a burst costs one leading publish, which is what makes a
    single edit feel instant, and one trailing publish, which is what stops
    the last write of the burst being the one that never arrives.

    The lease's timeout is a backstop for a trailing task that never runs, not
    the thing that ends the window: ``publish_trailing_data_versions`` deletes
    the key before it reads the versions, so the window closes at the moment
    the trailing payload is computed rather than at a TTL two hosts' clocks
    have to agree on.
    """
    try:
        if not caches["shared"].add(PUBLISH_LOCK_KEY, True, timeout=PUBLISH_COALESCE_SECONDS):
            return

        publish_data_versions_now()

        # Imported at call time: tasks.py imports this module for the publish
        # implementation, so a module-level import here is a cycle.
        from apps.operations.tasks import publish_data_versions_task  # noqa: PLC0415

        publish_data_versions_task.apply_async(countdown=PUBLISH_COALESCE_SECONDS)
    except Exception as exc:
        logger.exception("Failed to publish data versions after commit.")
        persist_app_error(
            exc,
            AppErrorContext(additional_context={"channel": settings.DATA_VERSIONS_CHANNEL}),
        )
        raise


def publish_data_versions_after_commit() -> None:
    """Queue one publish for after the current transaction commits.

    Publishing inside the transaction would advertise versions computed from
    the writer's own uncommitted rows, so a listener would refetch and get the
    state it already had — and then never be told again.

    Registered at most once per transaction. Every saved row calls this, and a
    bulk sync commits thousands in one transaction; without the check each of
    those queues a callback whose whole body is a Redis round-trip to discover
    the coalescing lock is held.

    ``robust=True`` because Django abandons every remaining on-commit callback
    once one raises. This one is registered by ``post_save``, so it runs BEFORE
    the callbacks services register later in the same transaction — a Redis
    blip here would otherwise cancel their work after the data had committed.
    The failure is still persisted and logged inside the callback.
    """
    connection = transaction.get_connection()
    # Indexed rather than unpacked: the entry gained a third member (robust) in
    # Django 4.2 and django-stubs still declares the two-member shape, so an
    # unpack is a type error against a tuple whose second member is the
    # callable either way.
    already_registered = any(
        entry[1] is schedule_data_versions_publish for entry in connection.run_on_commit
    )
    if already_registered:
        return
    transaction.on_commit(schedule_data_versions_publish, robust=True)


def _on_source_model_changed(**_kwargs: object) -> None:
    """Signal receiver for every source model's saves and deletes."""
    publish_data_versions_after_commit()


def _source_models() -> list[type[Model]]:
    """Each source model once, in registry order."""
    return list(dict.fromkeys(chain.from_iterable(DATA_VERSION_SOURCE_MODELS.values())))


def connect_data_version_signals() -> None:
    """Wire the source models and the observer seam. Called from ``ready()``."""
    for model in _source_models():
        post_save.connect(_on_source_model_changed, sender=model, dispatch_uid=_SIGNAL_DISPATCH_UID)
        post_delete.connect(
            _on_source_model_changed, sender=model, dispatch_uid=_SIGNAL_DISPATCH_UID
        )
    register_publisher(publish_data_versions_after_commit)
