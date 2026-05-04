import logging

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register
from django.db import models
from django.utils.autoreload import autoreload_started

logger = logging.getLogger(__name__)


def _watch_git_head(sender, **kwargs) -> None:
    # `.git/logs/HEAD` is appended on every HEAD-moving op (commit, checkout,
    # reset, merge, rebase). Watching it makes runserver re-import settings so
    # BUILD_ID stays in sync with the frontend's per-request read of HEAD.
    git_log = settings.BASE_DIR / ".git" / "logs" / "HEAD"
    if git_log.exists():
        sender.extra_files.add(git_log)


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
        if settings.DEBUG and not settings.SKIP_VERSION_CHECK:
            autoreload_started.connect(_watch_git_head)

    @staticmethod
    def _register_accounting_providers() -> None:
        """Import accounting provider modules so they auto-register."""
        import apps.workflow.accounting.xero.provider  # noqa: F401
