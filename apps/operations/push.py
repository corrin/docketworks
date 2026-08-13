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

Nothing here is wrapped in an error handler. Publishing needs the shared Redis
cache and Redis pub/sub, and an instance that has lost Redis has already lost
celery, django-solo propagation and the session cache — swallowing the failure
would trade a loud outage for silently stale tabs (ADR 0015).
"""

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
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.job.models import Job
from apps.operations.api import current_data_versions
from apps.purchasing.models import Stock

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


def schedule_data_versions_publish() -> None:
    """Publish immediately, and once more when the write burst settles.

    ``cache.add`` on the shared (Redis) cache is the deduplication: it
    succeeds for exactly one caller per window across every worker process and
    celery worker. So a burst costs one leading publish, which is what makes a
    single edit feel instant, and one trailing publish, which is what stops
    the last write of the burst being the one that never arrives.
    """
    if not caches["shared"].add(PUBLISH_LOCK_KEY, True, timeout=PUBLISH_COALESCE_SECONDS):
        return

    publish_data_versions_now()

    # Imported at call time: tasks.py imports this module for the publish
    # implementation, so a module-level import here is a cycle.
    from apps.operations.tasks import publish_data_versions_task  # noqa: PLC0415

    publish_data_versions_task.apply_async(countdown=PUBLISH_COALESCE_SECONDS)


def publish_data_versions_after_commit() -> None:
    """Queue a publish for after the current transaction commits.

    Publishing inside the transaction would advertise versions computed from
    the writer's own uncommitted rows, so a listener would refetch and get the
    state it already had — and then never be told again.
    """
    transaction.on_commit(schedule_data_versions_publish)


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
