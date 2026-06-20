from unittest.mock import patch

from apps.job.models import LabourSubtype
from apps.testing import BaseTestCase
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models.app_error import AppError


class CreateDefaultTaskTests(BaseTestCase):
    """create_default_task looks up the Workshop charge-out rate before the
    external Xero call. A missing Workshop subtype must not crash silently
    (ADR 0019): it persists an AppError and re-raises AlreadyLoggedException."""

    def test_missing_workshop_subtype_persists_app_error(self) -> None:
        from apps.workflow.api.xero import xero

        # Force default_workshop() to raise by removing every active workshop
        # subtype seeded by migrations.
        LabourSubtype.objects.filter(is_workshop=True).update(is_active=False)
        before = AppError.objects.count()

        with (
            patch.object(xero, "get_tenant_id", return_value="tenant"),
            patch.object(xero, "ProjectApi") as mock_project_api,
        ):
            with self.assertRaises(AlreadyLoggedException):
                xero.create_default_task("project-id")

        # The Xero task must never be attempted once the rate lookup fails.
        mock_project_api.return_value.create_task.assert_not_called()
        self.assertEqual(AppError.objects.count(), before + 1)
