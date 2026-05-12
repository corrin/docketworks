from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from django.test import SimpleTestCase

from apps.workflow.api.xero.payroll import (
    DraftPayRunBlocksLeaveDeletion,
    _delete_existing_leave_for_week,
    reconcile_leave_for_staff_week,
    reconcile_leave_for_week_for_staff,
)


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

    @patch("apps.workflow.api.xero.payroll.create_employee_leave")
    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id", return_value="tenant-1")
    def test_reconcile_keeps_matching_existing_leave(
        self,
        mock_get_tenant_id,
        mock_payroll_api_cls,
        mock_create_employee_leave,
    ):
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.get_employee_leaves.return_value = SimpleNamespace(
            leave=[
                SimpleNamespace(
                    leave_id="leave-1",
                    leave_type_id="sick-type-1",
                    start_date=date(2025, 5, 7),
                    end_date=date(2025, 5, 7),
                    periods=[
                        SimpleNamespace(
                            number_of_units=8.0,
                            number_of_units_taken=None,
                        )
                    ],
                )
            ]
        )
        entries = [
            SimpleNamespace(
                id="costline-1",
                accounting_date=date(2025, 5, 7),
                quantity=Decimal("8.000"),
                xero_pay_item=SimpleNamespace(
                    xero_id="sick-type-1",
                    name="Sick Leave",
                ),
            )
        ]

        leave_ids = reconcile_leave_for_staff_week(
            UUID("3a2e113b-425e-5e48-b5e5-a596cb4fb2d6"),
            entries,
            date(2025, 5, 5),
            date(2025, 5, 11),
        )

        self.assertEqual(leave_ids, ["leave-1"])
        payroll_api.delete_employee_leave.assert_not_called()
        mock_create_employee_leave.assert_not_called()

    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id", return_value="tenant-1")
    def test_raises_draft_pay_run_leave_delete_block(
        self,
        mock_get_tenant_id,
        mock_payroll_api_cls,
    ):
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.get_employee_leaves.return_value = SimpleNamespace(
            leave=[
                SimpleNamespace(
                    leave_id="leave-1",
                    start_date=date(2025, 5, 7),
                    end_date=date(2025, 5, 7),
                )
            ]
        )
        payroll_api.delete_employee_leave.side_effect = Exception(
            "Could not delete the leave request. There is a draft pay run "
            "for this employee."
        )

        with self.assertRaisesRegex(
            DraftPayRunBlocksLeaveDeletion, "existing leave request"
        ):
            _delete_existing_leave_for_week(
                UUID("3a2e113b-425e-5e48-b5e5-a596cb4fb2d6"),
                date(2025, 5, 5),
                date(2025, 5, 11),
            )

    @patch("apps.accounts.models.Staff.objects.in_bulk")
    @patch("apps.workflow.api.xero.payroll.delete_same_week_draft_pay_run")
    @patch("apps.workflow.api.xero.payroll.reconcile_leave_for_staff_week")
    @patch("apps.job.models.costing.CostLine.objects.filter")
    def test_deletes_same_week_draft_and_retries_leave_cleanup(
        self,
        mock_costline_filter,
        mock_reconcile_leave,
        mock_delete_draft_pay_run,
        mock_staff_in_bulk,
    ):
        staff_id = UUID("1833d340-b4dc-5870-acf9-41791be7fd8d")
        mock_staff_in_bulk.return_value = {
            staff_id: SimpleNamespace(
                email="timothy.harris@example.com",
                xero_user_id="55de6fd8-a845-4c27-94d8-841ddb815db3",
            )
        }
        queryset = MagicMock()
        queryset.select_related.return_value = []
        mock_costline_filter.return_value = queryset
        mock_reconcile_leave.side_effect = [
            DraftPayRunBlocksLeaveDeletion("blocked"),
            ["leave-1"],
        ]
        mock_delete_draft_pay_run.return_value = "payrun-1"

        leave_ids = reconcile_leave_for_week_for_staff(
            [staff_id],
            date(2025, 5, 5),
        )

        self.assertEqual(leave_ids, ["leave-1"])
        mock_delete_draft_pay_run.assert_called_once_with(date(2025, 5, 5))
        self.assertEqual(mock_reconcile_leave.call_count, 2)
