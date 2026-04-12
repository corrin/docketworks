import logging

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register
from django.db import models

from apps.workflow.scheduler import get_scheduler

# Import standalone job functions
from apps.workflow.scheduler_jobs import (
    xero_30_day_sync_job,
    xero_heartbeat_job,
    xero_regular_sync_job,
)

logger = logging.getLogger(__name__)


@register()
def check_company_defaults_field_sections(app_configs, **kwargs):
    """
    Verify all CompanyDefaults fields have section metadata defined.

    This ensures new fields are properly categorized for the settings UI.
    """
    from apps.workflow.models import CompanyDefaults
    from apps.workflow.models.settings_metadata import COMPANY_DEFAULTS_FIELD_SECTIONS

    errors = []
    for field in CompanyDefaults._meta.get_fields():
        if not isinstance(field, models.Field):
            continue
        if field.name not in COMPANY_DEFAULTS_FIELD_SECTIONS:
            errors.append(
                Error(
                    f"CompanyDefaults field '{field.name}' has no section defined",
                    hint=(
                        f"Add '{field.name}' to COMPANY_DEFAULTS_FIELD_SECTIONS in "
                        f"apps/workflow/models/settings_metadata.py"
                    ),
                    obj=CompanyDefaults,
                    id="workflow.E001",
                )
            )
    return errors


class WorkflowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workflow"
    verbose_name = "Workflow"

    def ready(self) -> None:
        self._register_accounting_providers()

        if settings.RUN_SCHEDULER:
            self._register_xero_jobs()

    @staticmethod
    def _register_accounting_providers() -> None:
        """Import accounting provider modules so they auto-register."""
        import apps.workflow.accounting.xero.provider  # noqa: F401

    def _register_xero_jobs(self) -> None:
        """Register Xero-related jobs with the shared scheduler."""
        scheduler = get_scheduler()

        # Xero Heartbeat: Refresh Xero API token every 5 minutes
        scheduler.add_job(
            xero_heartbeat_job,  # Use standalone function
            trigger="interval",
            minutes=5,
            id="xero_heartbeat",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=60,  # 1 minute grace time
            coalesce=True,
        )
        logger.info("Added 'xero_heartbeat' job to shared scheduler.")

        # Xero Regular Sync: Perform full Xero synchronization hourly
        scheduler.add_job(
            xero_regular_sync_job,  # Use standalone function
            trigger="interval",
            hours=1,
            id="xero_regular_sync",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=60 * 60,  # 1 hour grace time
            coalesce=True,
        )
        logger.info("Added 'xero_regular_sync' job to shared scheduler.")

        # Xero 30-Day Sync: Perform full Xero synchronization on Saturday morning
        # every ~30 days
        scheduler.add_job(
            xero_30_day_sync_job,  # Use standalone function
            trigger="cron",
            day_of_week="sat",  # Saturday
            hour=2,  # 2 AM
            minute=0,
            timezone="Pacific/Auckland",  # Explicitly set NZT
            id="xero_30_day_sync",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=24 * 60 * 60,  # 24 hour grace time
            coalesce=True,
        )
        logger.info(
            "Added 'xero_30_day_sync' job to shared scheduler (Saturday morning)."
        )
