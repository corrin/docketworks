"""Manual time-entry command builders must produce valid time CostLines.

Regression guard for KAN-326's second defect: the manual backfill commands
(create_leave_entries, create_overtime_entries, reclassify_overtime_entries)
hand-rolled CostLine creation without labour_subtype, which CostLine.clean()
has required for time lines since KAN-230 — so every run crashed on the
first save while --dry-run reported success. The builders under test are
shared by the dry-run and real paths (dry-run now saves inside a rolled-back
transaction), so saving a built line here exercises exactly the validation a
live run hits.
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import CommandError
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import CostSet, Job
from apps.testing import BaseTestCase
from apps.timesheet.management.commands.create_leave_entries import (
    build_leave_cost_line,
)
from apps.timesheet.management.commands.create_overtime_entries import (
    build_manual_time_cost_line,
)
from apps.workflow.models import XeroPayItem


class ManualTimeEntryBuilderTestCase(BaseTestCase):
    def setUp(self) -> None:
        self.company = Company.objects.create(
            name="Leave Test Company",
            email="leave-tests@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.staff = Staff.objects.create_user(
            email="leave-taker@example.com",
            password="testpass",
            first_name="Leave",
            last_name="Taker",
            is_workshop_staff=True,
            base_wage_rate=Decimal("30.00"),
        )
        self.pay_item = XeroPayItem.objects.create(
            xero_id="test-sick-leave-item",
            xero_tenant_id="test-tenant",
            name="Test Sick Leave",
            uses_leave_api=True,
            multiplier=Decimal("1.00"),
            xero_last_modified=timezone.now(),
        )
        self.job = Job(
            name="Sick Leave",
            company=self.company,
            status="special",
            default_xero_pay_item=self.pay_item,
        )
        self.job.save(staff=Staff.get_automation_user())
        self.cost_set = CostSet.objects.get_or_create(
            job=self.job, kind="actual", rev=1, defaults={"summary": {}}
        )[0]

    def _clear_default_subtype(self) -> None:
        # update() bypasses Staff.save(), which would re-set the default.
        Staff.objects.filter(id=self.staff.id).update(default_labour_subtype=None)
        self.staff.refresh_from_db()


class BuildLeaveCostLineTests(ManualTimeEntryBuilderTestCase):
    def test_line_carries_staff_default_subtype_and_saves(self) -> None:
        """The exact regression that shipped: leave lines must carry
        labour_subtype (from the staff default) and survive the model's
        full_clean-on-save, or the command crashes on its first entry."""
        line = build_leave_cost_line(
            self.staff,
            self.cost_set,
            self.job,
            "sick",
            date(2026, 7, 28),
            Decimal("4.500"),
        )

        self.assertIsNotNone(self.staff.default_labour_subtype)
        self.assertEqual(line.labour_subtype, self.staff.default_labour_subtype)
        line.save()
        line.refresh_from_db()
        self.assertEqual(line.kind, "time")
        self.assertEqual(line.quantity, Decimal("4.500"))
        self.assertEqual(line.unit_cost, Decimal("30.00"))

    def test_missing_default_subtype_fails_at_validation_time(self) -> None:
        """A staff row without default_labour_subtype must fail while the
        command is still validating — i.e. --dry-run catches it — with an
        error naming the staff member, not a mid-write crash."""
        self._clear_default_subtype()

        with self.assertRaisesRegex(CommandError, "Leave Taker"):
            build_leave_cost_line(
                self.staff,
                self.cost_set,
                self.job,
                "sick",
                date(2026, 7, 28),
                Decimal("8.000"),
            )


class BuildManualTimeCostLineTests(ManualTimeEntryBuilderTestCase):
    def test_line_carries_staff_default_subtype_and_saves(self) -> None:
        """create_overtime_entries shares the same defect class; its builder
        must produce lines that pass model validation and save."""
        line = build_manual_time_cost_line(
            staff=self.staff,
            cost_set=self.cost_set,
            desc="Retrospectively added OT - Leave Taker",
            hours=Decimal("2.000"),
            unit_cost=Decimal("45.00"),
            accounting_date=date(2026, 7, 28),
            pay_item=self.pay_item,
            wage_rate_multiplier=1.5,
        )

        self.assertEqual(line.labour_subtype, self.staff.default_labour_subtype)
        self.assertEqual(line.meta["wage_rate_multiplier"], 1.5)
        line.save()
        line.refresh_from_db()
        self.assertEqual(line.quantity, Decimal("2.000"))

    def test_missing_default_subtype_fails_at_validation_time(self) -> None:
        self._clear_default_subtype()

        with self.assertRaisesRegex(CommandError, "Leave Taker"):
            build_manual_time_cost_line(
                staff=self.staff,
                cost_set=self.cost_set,
                desc="Retrospectively added OT - Leave Taker",
                hours=Decimal("2.000"),
                unit_cost=Decimal("45.00"),
                accounting_date=date(2026, 7, 28),
                pay_item=self.pay_item,
                wage_rate_multiplier=1.5,
            )
