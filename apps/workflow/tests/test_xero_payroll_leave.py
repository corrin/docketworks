"""Leave reconciliation against Xero NZ Payroll (KAN-326).

These tests build Xero-side echoes and capture outbound payloads with the REAL
xero_python models — only the transport (PayrollNzApi methods, get_tenant_id,
time.sleep) is mocked. The prod incident survived the old suite precisely
because the payload construction was mocked out: a real PayRun model would
have raised on pay_run_status="Deleted" in any test that exercised it.
"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from xero_python.payrollnz.models import EmployeeLeave, LeavePeriod

from apps.job.models.costing import CostLine
from apps.workflow.api.xero.payroll import (
    DraftPayRunBlocksLeaveChange,
    _build_leave_requests,
    create_employee_leave,
    reconcile_leave_for_staff_week,
    reconcile_leave_for_week_for_staff,
)
from apps.workflow.models import XeroPayItem, XeroPayRun

EMPLOYEE_ID = UUID("3a2e113b-425e-5e48-b5e5-a596cb4fb2d6")
WEEK_START = date(2026, 7, 27)
WEEK_END = date(2026, 8, 2)
SICK_TYPE = "sick-type-1"

# Captured live from the Xero NZ API on 2026-08-02 (KAN-326).
DRAFT_BLOCK_MESSAGE = (
    "Could not delete the leave request. There is a draft pay run " "for this employee."
)


def _cost_line(day: date, hours: str) -> CostLine:
    return CostLine(
        kind="time",
        accounting_date=day,
        quantity=Decimal(hours),
        xero_pay_item=XeroPayItem(
            xero_id=SICK_TYPE, name="Sick Leave", uses_leave_api=True
        ),
    )


def _xero_leave(
    leave_id: str,
    start: date,
    end: date,
    total_units: float,
    leave_type_id: str = SICK_TYPE,
) -> EmployeeLeave:
    """A leave record as Xero actually returns it: one lumped period per pay
    week carrying only the total units (per-day breakdowns are not preserved).
    """
    return EmployeeLeave(
        leave_id=leave_id,
        leave_type_id=leave_type_id,
        description="Sick Leave",
        start_date=datetime(start.year, start.month, start.day),
        end_date=datetime(end.year, end.month, end.day),
        periods=[
            LeavePeriod(
                period_start_date=WEEK_START,
                period_end_date=WEEK_END,
                number_of_units=total_units,
                period_status="Approved",
            )
        ],
    )


class BuildLeaveRequestsTests(SimpleTestCase):
    def test_single_request_for_mixed_hours(self) -> None:
        """The prod incident's structural mismatch: a contiguous run with
        non-uniform daily hours must stay ONE request carrying the total, not
        split into one request per distinct hours value."""
        specs = _build_leave_requests(
            [
                _cost_line(date(2026, 7, 28), "4.5"),
                _cost_line(date(2026, 7, 29), "8"),
                _cost_line(date(2026, 7, 30), "8"),
                _cost_line(date(2026, 7, 31), "8"),
            ]
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["start_date"], date(2026, 7, 28))
        self.assertEqual(specs[0]["end_date"], date(2026, 7, 31))
        self.assertEqual(specs[0]["total_units"], Decimal("28.500"))

    def test_splits_on_date_gap(self) -> None:
        """Non-contiguous leave days become separate requests."""
        specs = _build_leave_requests(
            [
                _cost_line(date(2026, 7, 27), "8"),
                _cost_line(date(2026, 7, 28), "8"),
                _cost_line(date(2026, 7, 30), "8"),
            ]
        )

        self.assertEqual(
            [(s["start_date"], s["end_date"], s["total_units"]) for s in specs],
            [
                (date(2026, 7, 27), date(2026, 7, 28), Decimal("16.000")),
                (date(2026, 7, 30), date(2026, 7, 30), Decimal("8.000")),
            ],
        )

    def test_sums_same_day_entries(self) -> None:
        """Two cost lines on the same day merge into one request instead of
        producing overlapping duplicate leave requests in Xero."""
        specs = _build_leave_requests(
            [
                _cost_line(date(2026, 7, 28), "4"),
                _cost_line(date(2026, 7, 28), "4"),
            ]
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["total_units"], Decimal("8.000"))


@patch("apps.workflow.api.xero.payroll.time.sleep")
@patch("apps.workflow.api.xero.payroll.PayrollNzApi")
@patch("apps.workflow.api.xero.payroll.get_tenant_id", return_value="tenant-1")
class ReconcileLeaveTests(SimpleTestCase):
    def test_keeps_lumped_mixed_hours_leave(
        self,
        mock_get_tenant_id: MagicMock,
        mock_payroll_api_cls: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Regression for the prod incident: a 28.5h lumped Xero leave over a
        4.5/8/8/8 timesheet week must key-match and be left untouched. The old
        per-day differ declared it permanently obsolete and deleted it on
        every payroll run."""
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.get_employee_leaves.return_value = SimpleNamespace(
            leave=[_xero_leave("leave-1", date(2026, 7, 28), date(2026, 7, 31), 28.5)]
        )
        entries = [
            _cost_line(date(2026, 7, 28), "4.5"),
            _cost_line(date(2026, 7, 29), "8"),
            _cost_line(date(2026, 7, 30), "8"),
            _cost_line(date(2026, 7, 31), "8"),
        ]

        leave_ids = reconcile_leave_for_staff_week(
            EMPLOYEE_ID, entries, WEEK_START, WEEK_END
        )

        self.assertEqual(leave_ids, ["leave-1"])
        payroll_api.delete_employee_leave.assert_not_called()
        payroll_api.update_employee_leave.assert_not_called()
        payroll_api.create_employee_leave.assert_not_called()

    def test_updates_changed_leave_in_place(
        self,
        mock_get_tenant_id: MagicMock,
        mock_payroll_api_cls: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Changed leave of the same type and overlapping span is updated in
        place (permitted during a draft pay run), never deleted-and-recreated."""
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.get_employee_leaves.return_value = SimpleNamespace(
            leave=[_xero_leave("leave-1", date(2026, 7, 27), date(2026, 7, 30), 32.0)]
        )
        payroll_api.update_employee_leave.return_value = SimpleNamespace(
            leave=_xero_leave("leave-1", date(2026, 7, 28), date(2026, 7, 31), 28.5)
        )
        entries = [
            _cost_line(date(2026, 7, 28), "4.5"),
            _cost_line(date(2026, 7, 29), "8"),
            _cost_line(date(2026, 7, 30), "8"),
            _cost_line(date(2026, 7, 31), "8"),
        ]

        leave_ids = reconcile_leave_for_staff_week(
            EMPLOYEE_ID, entries, WEEK_START, WEEK_END
        )

        self.assertEqual(leave_ids, ["leave-1"])
        payroll_api.delete_employee_leave.assert_not_called()
        payroll_api.create_employee_leave.assert_not_called()
        payroll_api.update_employee_leave.assert_called_once()
        call = payroll_api.update_employee_leave.call_args
        self.assertEqual(call.kwargs["leave_id"], "leave-1")
        payload = call.kwargs["employee_leave"]
        self.assertIsInstance(payload, EmployeeLeave)
        self.assertEqual(payload.start_date, date(2026, 7, 28))
        self.assertEqual(payload.end_date, date(2026, 7, 31))
        self.assertEqual(len(payload.periods), 1)
        self.assertEqual(payload.periods[0].period_start_date, WEEK_START)
        self.assertEqual(payload.periods[0].period_end_date, WEEK_END)
        self.assertEqual(payload.periods[0].number_of_units, 28.5)


class ReconcileBlockedChangeTests(TestCase):
    @patch("apps.workflow.api.xero.payroll.time.sleep")
    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id", return_value="tenant-1")
    def test_blocked_delete_raises_actionable_error(
        self,
        mock_get_tenant_id: MagicMock,
        mock_payroll_api_cls: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """When Xero blocks a required leave deletion, the operator gets told
        which draft pay run to delete in the Xero UI — replacing the removed
        auto-delete path, which was impossible (the NZ Payroll API has no
        pay-run delete endpoint) and crashed every payroll run."""
        XeroPayRun.objects.create(
            xero_id=UUID("17d7ca66-ee10-4e8a-918f-f8a5a890d1ac"),
            xero_tenant_id="tenant-1",
            period_start_date=WEEK_START,
            period_end_date=WEEK_END,
            payment_date=WEEK_END,
            pay_run_status="Draft",
            raw_json={},
            xero_last_modified=timezone.now(),
        )
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.get_employee_leaves.return_value = SimpleNamespace(
            leave=[_xero_leave("leave-1", date(2026, 7, 28), date(2026, 7, 31), 28.5)]
        )
        payroll_api.delete_employee_leave.side_effect = Exception(DRAFT_BLOCK_MESSAGE)

        with self.assertRaises(DraftPayRunBlocksLeaveChange) as ctx:
            reconcile_leave_for_staff_week(EMPLOYEE_ID, [], WEEK_START, WEEK_END)

        message = str(ctx.exception)
        self.assertIn("leave-1", message)
        self.assertIn("Payroll → Pay runs", message)
        self.assertIn(f"{WEEK_START} to {WEEK_END}", message)
        self.assertIsNotNone(ctx.exception.__cause__)
        # The old recovery path went on to PUT /PayRuns/{id}; nothing may
        # touch pay runs now.
        payroll_api.get_pay_runs.assert_not_called()
        payroll_api.create_pay_run.assert_not_called()

    @patch("apps.workflow.api.xero.payroll.time.sleep")
    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id", return_value="tenant-1")
    def test_unrelated_delete_failure_propagates_untranslated(
        self,
        mock_get_tenant_id: MagicMock,
        mock_payroll_api_cls: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Only the draft-pay-run block gets the operator guidance; any other
        Xero failure must surface as itself."""
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.get_employee_leaves.return_value = SimpleNamespace(
            leave=[_xero_leave("leave-1", date(2026, 7, 28), date(2026, 7, 31), 28.5)]
        )
        payroll_api.delete_employee_leave.side_effect = Exception("rate limited")

        with self.assertRaisesRegex(Exception, "rate limited"):
            reconcile_leave_for_staff_week(EMPLOYEE_ID, [], WEEK_START, WEEK_END)


class CreateEmployeeLeaveTests(SimpleTestCase):
    @patch("apps.workflow.api.xero.payroll.PayrollNzApi")
    @patch("apps.workflow.api.xero.payroll.get_tenant_id", return_value="tenant-1")
    def test_builds_single_lumped_period(
        self,
        mock_get_tenant_id: MagicMock,
        mock_payroll_api_cls: MagicMock,
    ) -> None:
        """The only payload shape Xero honours (verified live 2026-08-02):
        one period spanning the payroll week carrying the total units. Per-day
        periods are accepted but their units silently discarded."""
        payroll_api = mock_payroll_api_cls.return_value
        payroll_api.create_employee_leave.return_value = SimpleNamespace(
            leave=_xero_leave("leave-9", date(2026, 7, 28), date(2026, 7, 31), 28.5)
        )

        leave_id = create_employee_leave(
            employee_id=EMPLOYEE_ID,
            leave_type_id=SICK_TYPE,
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 31),
            total_units=Decimal("28.500"),
            week_start_date=WEEK_START,
            week_end_date=WEEK_END,
            description="Sick Leave",
        )

        self.assertEqual(leave_id, "leave-9")
        payload = payroll_api.create_employee_leave.call_args.kwargs["employee_leave"]
        self.assertIsInstance(payload, EmployeeLeave)
        self.assertEqual(payload.start_date, date(2026, 7, 28))
        self.assertEqual(payload.end_date, date(2026, 7, 31))
        self.assertEqual(len(payload.periods), 1)
        self.assertEqual(payload.periods[0].period_start_date, WEEK_START)
        self.assertEqual(payload.periods[0].period_end_date, WEEK_END)
        self.assertEqual(payload.periods[0].number_of_units, 28.5)
        self.assertEqual(payload.periods[0].period_status, "Approved")


class OrchestratorTests(SimpleTestCase):
    @patch("apps.accounts.models.Staff.objects.in_bulk")
    @patch("apps.workflow.api.xero.payroll.reconcile_leave_for_staff_week")
    @patch("apps.job.models.costing.CostLine.objects.filter")
    def test_propagates_block_with_staff_name(
        self,
        mock_costline_filter: MagicMock,
        mock_reconcile_leave: MagicMock,
        mock_staff_in_bulk: MagicMock,
    ) -> None:
        """The per-staff reconciler only knows the Xero employee UUID; the
        orchestrator must name the staff member for the operator, chain the
        cause, and never retry (the old auto-delete retry is gone)."""
        staff_id = UUID("1833d340-b4dc-5870-acf9-41791be7fd8d")
        mock_staff_in_bulk.return_value = {
            staff_id: SimpleNamespace(
                email="timothy.harris@example.com",
                xero_user_id="55de6fd8-a845-4c27-94d8-841ddb815db3",
                get_display_full_name=lambda: "Timothy Harris",
            )
        }
        queryset = MagicMock()
        queryset.select_related.return_value = []
        mock_costline_filter.return_value = queryset
        mock_reconcile_leave.side_effect = DraftPayRunBlocksLeaveChange("blocked")

        with self.assertRaises(DraftPayRunBlocksLeaveChange) as ctx:
            reconcile_leave_for_week_for_staff([staff_id], date(2026, 7, 27))

        self.assertIn("Timothy Harris", str(ctx.exception))
        self.assertIn("blocked", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, DraftPayRunBlocksLeaveChange)
        mock_reconcile_leave.assert_called_once()
