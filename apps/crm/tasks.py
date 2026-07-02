import logging

from celery import shared_task
from django.db import close_old_connections

from apps.crm.models import PhoneProviderSettings
from apps.workflow.exceptions import AlreadyLoggedException
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
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        scheduler_logger.error("Error during phone call sync: %s", exc, exc_info=True)
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc


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
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        scheduler_logger.error(
            "Error during phone recording provider cleanup: %s",
            exc,
            exc_info=True,
        )
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc
