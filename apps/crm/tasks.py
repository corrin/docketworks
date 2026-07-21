import logging
from typing import Protocol, cast

from celery import shared_task
from django.db import close_old_connections

from apps.crm.models import PhoneProviderSettings
from apps.workflow.services.error_persistence import persist_app_error

scheduler_logger = logging.getLogger("apps.crm.tasks")


@shared_task(name="apps.crm.tasks.sync_phone_calls_task")
def sync_phone_calls_task() -> None:
    """Beat-scheduled recent phone call and recording archive."""
    scheduler_logger.info("Running sync_phone_calls_task.")
    try:
        close_old_connections()
        phone_settings = PhoneProviderSettings.get_solo()
        if not phone_settings.downloads_enabled:
            scheduler_logger.info("Phone call download disabled by CRM phone settings.")
            return

        from apps.crm.services.phone_call_service import sync_recent_calls

        result = sync_recent_calls()
        scheduler_logger.info(
            "Phone call sync complete: pages_fetched=%s calls_seen=%s calls_saved=%s "
            "recordings_seen=%s recordings_archived=%s",
            result.pages_fetched,
            result.calls_seen,
            result.calls_saved,
            result.recordings_seen,
            result.recordings_archived,
        )
    except Exception as exc:
        scheduler_logger.error("Error during phone call sync: %s", exc, exc_info=True)
        persist_app_error(exc)
        raise


@shared_task(name="apps.crm.tasks.delete_archived_phone_recordings_task")
def delete_archived_phone_recordings_task(limit: int = 100) -> None:
    """Delete provider-side recordings after local archive and configured delay."""
    scheduler_logger.info("Running delete_archived_phone_recordings_task.")
    try:
        close_old_connections()
        phone_settings = PhoneProviderSettings.get_solo()
        if not phone_settings.recording_deletion_enabled:
            scheduler_logger.info(
                "Phone recording provider cleanup disabled by CRM phone settings."
            )
            return

        from apps.crm.services.phone_call_service import (
            delete_archived_provider_recordings,
        )

        result = delete_archived_provider_recordings(limit=limit)
        scheduler_logger.info(
            "Phone recording provider cleanup complete: candidates=%s deleted=%s "
            "failed=%s",
            result.candidates,
            result.deleted,
            result.failed,
        )
    except Exception as exc:
        scheduler_logger.error(
            "Error during phone recording provider cleanup: %s",
            exc,
            exc_info=True,
        )
        persist_app_error(exc)
        raise


class RematchPhoneCallsTask(Protocol):
    def __call__(self, numbers: list[str]) -> None: ...

    def delay(self, numbers: list[str]) -> object: ...


def _rematch_phone_calls_task(numbers: list[str]) -> None:
    """Idempotently reclassify historical calls affected by phone-number changes.

    Unlike the beat-only tasks above, this one is also executed eagerly inside
    web requests (CELERY_TASK_ALWAYS_EAGER in dev/E2E/tests), so it must not
    call close_old_connections() — that would close the caller's in-flight
    connection. Real workers get connection hygiene from Celery's Django fixup.
    """
    scheduler_logger.info(
        "Running rematch_phone_calls_task for %d numbers.", len(numbers)
    )
    try:
        from apps.crm.services.phone_call_service import rematch_calls_for_numbers

        rematch_calls_for_numbers(numbers)
    except Exception as exc:
        scheduler_logger.error(
            "Error during phone call rematch: %s",
            exc,
            exc_info=True,
        )
        persist_app_error(exc)
        raise


rematch_phone_calls_task = cast(
    RematchPhoneCallsTask,
    shared_task(name="apps.crm.tasks.rematch_phone_calls_task")(
        _rematch_phone_calls_task
    ),
)
