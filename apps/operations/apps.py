import logging

from django.apps import AppConfig
from django.conf import settings

from apps.workflow.scheduler import get_scheduler

logger = logging.getLogger(__name__)


class OperationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.operations"

    def ready(self) -> None:
        if settings.RUN_SCHEDULER:
            self._register_operations_jobs()

    def _register_operations_jobs(self) -> None:
        from apps.operations.scheduler_jobs import recompute_workshop_schedule

        scheduler = get_scheduler()
        scheduler.add_job(
            recompute_workshop_schedule,
            trigger="interval",
            hours=4,
            id="recompute_workshop_schedule",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=60 * 60,
            coalesce=True,
        )
        logger.info("Added 'recompute_workshop_schedule' to shared scheduler.")
