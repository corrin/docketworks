from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase

from apps.workflow.api.xero.payroll import _delete_existing_leave_for_week


class DeleteExistingLeaveForWeekTests(SimpleTestCase):
    @patch("apps.workflow.api.xero.payroll.time.sleep")
    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id", return_value="tenant-1")
    def test_accepts_datetime_leave_dates(
        self,
        mock_get_tenant_id,
        mock_payroll_api_cls,
        mock_sleep,
    ):
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.get_employee_leaves.return_value = SimpleNamespace(
            leave=[
                SimpleNamespace(
                    leave_id="leave-1",
                    start_date=datetime(2025, 5, 6, 0, 0),
                    end_date=datetime(2025, 5, 7, 0, 0),
                )
            ]
        )

        deleted = _delete_existing_leave_for_week(
            UUID("3a2e113b-425e-5e48-b5e5-a596cb4fb2d6"),
            date(2025, 5, 5),
            date(2025, 5, 11),
        )

        self.assertEqual(deleted, 1)
        payroll_api.delete_employee_leave.assert_called_once_with(
            xero_tenant_id="tenant-1",
            employee_id="3a2e113b-425e-5e48-b5e5-a596cb4fb2d6",
            leave_id="leave-1",
        )
