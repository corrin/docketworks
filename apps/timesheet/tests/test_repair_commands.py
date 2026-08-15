"""Tests for the timesheet repair management commands.

Each command gets its happy path plus the refusals that guard real data:
duplicate/dry-run behaviour, weekend and unknown-input refusals, quantity
mismatches, and ambiguous staff resolution.

XeroPayRun/XeroPaySlip are reached through the app registry: the layer
contract forbids apps.timesheet -> apps.xero imports.
"""

import csv
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
from django.apps import apps as django_apps
from django.core.management import CommandError, call_command
from django.db.models import Model

from apps.accounts.models import Staff
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.management.commands import create_overtime_entries as overtime_command_module
from apps.timesheet.management.commands import (
    reclassify_overtime_entries as reclassify_command_module,
)
from apps.timesheet.tests.conftest import make_staff, make_time_line

pytestmark = pytest.mark.django_db

# A Monday after the xero_hours CUTOFF_DATE (2025-08-11).
MONDAY = date(2026, 5, 4)
TUESDAY = date(2026, 5, 5)
WEDNESDAY = date(2026, 5, 6)
FRIDAY = date(2026, 5, 8)
# Xero weekly pay periods run Sunday-Saturday; this period maps onto MONDAY's week.
XERO_PERIOD_START = date(2026, 5, 3)
XERO_PERIOD_END = date(2026, 5, 9)
SYNC_TIME = datetime(2026, 5, 13, tzinfo=UTC)


def _run(command: str, *args: str) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def _make_special_job(name: str, creator: Staff) -> Job:
    """A special-status job on the shop company (how the real overhead jobs live)."""
    company = CompanyDefaults.get_solo().shop_company
    job = make_job(company, creator, name=name)
    # untracked_update() dodges the change-event machinery a status edit
    # through save(staff=...) would trigger; this is test bookkeeping.
    Job.objects.filter(pk=job.pk).untracked_update(status="special")
    job.refresh_from_db()
    return job


def _make_shop_time_line(
    job: Job, staff: Staff, *, accounting_date: date, hours: str = "8.000"
) -> CostLine:
    """A standard-rate, non-billable time line (shop jobs refuse revenue)."""
    return make_time_line(
        job,
        staff,
        accounting_date=accounting_date,
        hours=hours,
        unit_rev="0.00",
        is_billable=False,
    )


def _make_pay_run(*, status: str = "Posted") -> Model:
    return cast(
        "Model",
        django_apps.get_model("xero", "XeroPayRun")._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            period_start_date=XERO_PERIOD_START,
            period_end_date=XERO_PERIOD_END,
            payment_date=XERO_PERIOD_END,
            pay_run_status=status,
            raw_json={},
            xero_last_modified=SYNC_TIME,
        ),
    )


def _make_pay_slip(pay_run: Model, staff: Staff, raw_json: dict[str, object]) -> Model:
    if staff.xero_user_id is None:
        raise ValueError("test staff must carry a xero_user_id")
    return cast(
        "Model",
        django_apps.get_model("xero", "XeroPaySlip")._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            pay_run=pay_run,
            xero_employee_id=uuid.UUID(staff.xero_user_id),
            employee_name=staff.get_display_full_name(),
            raw_json=raw_json,
            xero_last_modified=SYNC_TIME,
        ),
    )


def _timesheet_line(name: str, units: str, rate: str = "40.0") -> dict[str, object]:
    return {"_display_name": name, "_number_of_units": units, "_rate_per_unit": rate}


@pytest.fixture
def creator() -> Staff:
    return make_staff(
        "repair-admin@example.com",
        is_office_staff=True,
        is_superuser=True,
        first_name="Repair",
        last_name="Admin",
    )


class TestCreateOvertimeEntries:
    """create_overtime_entries: preview proposes the gap; apply writes the CSV."""

    def test_preview_proposes_overtime_for_the_gap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, creator: Staff
    ) -> None:
        staff = make_staff("ot-w@example.com", first_name="Overta", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        _make_shop_time_line(shop_job, staff, accounting_date=TUESDAY)
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            staff,
            {
                "_timesheet_earnings_lines": [
                    _timesheet_line("Ordinary Time", "8"),
                    _timesheet_line("Time and one half", "4", "60.0"),
                ]
            },
        )
        preview_path = tmp_path / "overtime_preview.csv"
        monkeypatch.setattr(overtime_command_module, "PREVIEW_CSV_PATH", preview_path)

        output = _run("create_overtime_entries", "--preview")

        assert "Entries to create: 1 (1 OT, 0 ordinary, 0 leave)" in output
        with preview_path.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["entry_type"] == "overtime"
        assert rows[0]["hours_to_create"] == "4.000"
        assert rows[0]["job_name"] == "Shop Time"
        assert rows[0]["accounting_date"] == FRIDAY.isoformat()
        assert rows[0]["staff_id"] == str(staff.id)

    def test_preview_skips_matched_weeks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, creator: Staff
    ) -> None:
        staff = make_staff("ot-m@example.com", first_name="Matcha", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        _make_shop_time_line(shop_job, staff, accounting_date=TUESDAY)
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            staff,
            {"_timesheet_earnings_lines": [_timesheet_line("Ordinary Time", "8")]},
        )
        monkeypatch.setattr(
            overtime_command_module, "PREVIEW_CSV_PATH", tmp_path / "overtime_preview.csv"
        )

        output = _run("create_overtime_entries", "--preview")

        assert "Skipped (hours matched): 1" in output
        assert "Nothing to create." in output

    def test_apply_creates_overtime_and_ordinary_entries(
        self, tmp_path: Path, creator: Staff
    ) -> None:
        staff = make_staff("ot-a@example.com", first_name="Apply", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        base = {
            "week_start": MONDAY.isoformat(),
            "staff_name": staff.get_display_name(),
            "staff_id": str(staff.id),
            "accounting_date": FRIDAY.isoformat(),
            "job_name": shop_job.name,
            "job_id": str(shop_job.id),
            "unit_cost": "40.00",
            "xero_ot": "4",
            "jm_ot": "0",
            "xero_total": "14",
            "jm_total": "8",
            "headroom": "6.000",
        }
        csv_path = tmp_path / "reviewed.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=overtime_command_module.PREVIEW_COLUMNS)
            writer.writeheader()
            writer.writerow({**base, "entry_type": "overtime", "hours_to_create": "4.000"})
            writer.writerow({**base, "entry_type": "ordinary", "hours_to_create": "2.000"})

        output = _run("create_overtime_entries", "--apply", str(csv_path))

        assert "Created 1 OT + 1 ordinary + 0 leave = 2 total entries." in output
        lines = CostLine.objects.filter(cost_set=shop_job.latest_actual, staff=staff)
        by_hours = {line.quantity: line for line in lines}
        ot_line = by_hours[Decimal("4.000")]
        ordinary_line = by_hours[Decimal("2.000")]
        assert ot_line.xero_pay_item is not None
        assert ot_line.xero_pay_item.name == "Time and one half"
        assert ot_line.meta["wage_rate_multiplier"] == 1.5
        assert ot_line.desc == "Retrospectively added OT - Apply"
        assert ordinary_line.xero_pay_item is not None
        assert ordinary_line.xero_pay_item.name == "Ordinary Time"
        assert ordinary_line.meta["wage_rate_multiplier"] == 1.0
        assert ot_line.unit_cost == Decimal("40.00")

    def test_apply_refuses_unknown_entry_type(self, tmp_path: Path, creator: Staff) -> None:
        staff = make_staff("ot-b@example.com", first_name="Badrow", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        csv_path = tmp_path / "reviewed.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=overtime_command_module.PREVIEW_COLUMNS)
            writer.writeheader()
            writer.writerow(
                {
                    "week_start": MONDAY.isoformat(),
                    "staff_name": "Badrow",
                    "staff_id": str(staff.id),
                    "entry_type": "banana",
                    "hours_to_create": "4.000",
                    "accounting_date": FRIDAY.isoformat(),
                    "job_name": shop_job.name,
                    "job_id": str(shop_job.id),
                    "unit_cost": "40.00",
                    "xero_ot": "4",
                    "jm_ot": "0",
                    "xero_total": "12",
                    "jm_total": "8",
                    "headroom": "4.000",
                }
            )

        with pytest.raises(CommandError, match="entry_type must be"):
            _run("create_overtime_entries", "--apply", str(csv_path))
        assert not CostLine.objects.filter(cost_set=shop_job.latest_actual).exists()

    def test_refuses_both_steps_at_once(self) -> None:
        with pytest.raises(CommandError, match="not both"):
            _run("create_overtime_entries", "--preview", "--apply", "x.csv")

    def test_refuses_neither_step(self) -> None:
        with pytest.raises(CommandError, match="Specify --preview"):
            _run("create_overtime_entries")


class TestReclassifyOvertimeEntries:
    """reclassify_overtime_entries: reclassify/split existing standard-rate lines."""

    def test_preview_proposes_split_when_totals_match_but_ot_is_short(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, creator: Staff
    ) -> None:
        staff = make_staff("rc-p@example.com", first_name="Recla", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        line = _make_shop_time_line(shop_job, staff, accounting_date=TUESDAY)
        pay_run = _make_pay_run()
        _make_pay_slip(
            pay_run,
            staff,
            {
                "_timesheet_earnings_lines": [
                    _timesheet_line("Ordinary Time", "4"),
                    _timesheet_line("Time and one half", "4", "60.0"),
                ]
            },
        )
        preview_path = tmp_path / "reclassify_preview.csv"
        monkeypatch.setattr(reclassify_command_module, "PREVIEW_CSV_PATH", preview_path)

        output = _run("reclassify_overtime_entries", "--preview")

        assert "Entries to reclassify/split: 1" in output
        with preview_path.open() as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["action"] == "split"
        assert rows[0]["costline_id"] == str(line.id)
        assert rows[0]["ot_hours"] == "4"
        assert rows[0]["remaining_hours"] == "4.000"

    def test_apply_reclassifies_and_splits(self, tmp_path: Path, creator: Staff) -> None:
        staff = make_staff("rc-a@example.com", first_name="Splitty", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        split_line = _make_shop_time_line(shop_job, staff, accounting_date=TUESDAY)
        whole_line = _make_shop_time_line(shop_job, staff, accounting_date=WEDNESDAY, hours="4.000")
        csv_path = tmp_path / "reviewed.csv"
        base = {
            "week_start": MONDAY.isoformat(),
            "staff_name": staff.get_display_name(),
            "staff_id": str(staff.id),
            "job_name": shop_job.name,
            "job_id": str(shop_job.id),
            "unit_cost": "48.00",
            "xero_ot": "7",
            "jm_ot": "0",
            "ot_gap": "7",
        }
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=reclassify_command_module.PREVIEW_COLUMNS)
            writer.writeheader()
            writer.writerow(
                {
                    **base,
                    "costline_id": str(split_line.id),
                    "action": "split",
                    "ot_hours": "3",
                    "remaining_hours": "5",
                    "accounting_date": TUESDAY.isoformat(),
                }
            )
            writer.writerow(
                {
                    **base,
                    "costline_id": str(whole_line.id),
                    "action": "reclassify",
                    "ot_hours": "4",
                    "remaining_hours": "0",
                    "accounting_date": WEDNESDAY.isoformat(),
                }
            )

        output = _run("reclassify_overtime_entries", "--apply", str(csv_path))

        assert "Reclassified: 1, Split: 1, Total: 2" in output
        split_line.refresh_from_db()
        whole_line.refresh_from_db()
        assert split_line.quantity == Decimal("5.000")
        assert split_line.xero_pay_item is not None
        assert split_line.xero_pay_item.name == "Ordinary Time"
        assert whole_line.xero_pay_item is not None
        assert whole_line.xero_pay_item.name == "Time and one half"
        assert whole_line.desc == "Timesheet work [OT reclassified]"
        assert whole_line.meta["wage_rate_multiplier"] == 1.5
        new_line = CostLine.objects.get(
            cost_set=shop_job.latest_actual, staff=staff, quantity=Decimal("3.000")
        )
        assert new_line.xero_pay_item is not None
        assert new_line.xero_pay_item.name == "Time and one half"
        assert new_line.accounting_date == TUESDAY
        assert new_line.unit_cost == split_line.unit_cost

    def test_reapplying_the_same_csv_is_refused(self, tmp_path: Path, creator: Staff) -> None:
        staff = make_staff("rc-r@example.com", first_name="Reappl", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        line = _make_shop_time_line(shop_job, staff, accounting_date=WEDNESDAY, hours="4.000")
        csv_path = tmp_path / "reviewed.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=reclassify_command_module.PREVIEW_COLUMNS)
            writer.writeheader()
            writer.writerow(
                {
                    "week_start": MONDAY.isoformat(),
                    "staff_name": staff.get_display_name(),
                    "staff_id": str(staff.id),
                    "costline_id": str(line.id),
                    "action": "reclassify",
                    "ot_hours": "4",
                    "remaining_hours": "0",
                    "accounting_date": WEDNESDAY.isoformat(),
                    "job_name": shop_job.name,
                    "job_id": str(shop_job.id),
                    "unit_cost": "48.00",
                    "xero_ot": "4",
                    "jm_ot": "0",
                    "ot_gap": "4",
                }
            )

        _run("reclassify_overtime_entries", "--apply", str(csv_path))

        with pytest.raises(CommandError, match="already at an overtime rate"):
            _run("reclassify_overtime_entries", "--apply", str(csv_path))
        line.refresh_from_db()
        assert line.desc == "Timesheet work [OT reclassified]"
        assert line.meta["wage_rate_multiplier"] == 1.5

    def test_apply_refuses_quantity_mismatch(self, tmp_path: Path, creator: Staff) -> None:
        staff = make_staff("rc-m@example.com", first_name="Mismat", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        line = _make_shop_time_line(shop_job, staff, accounting_date=TUESDAY)
        csv_path = tmp_path / "reviewed.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=reclassify_command_module.PREVIEW_COLUMNS)
            writer.writeheader()
            writer.writerow(
                {
                    "week_start": MONDAY.isoformat(),
                    "staff_name": "Mismat",
                    "staff_id": str(staff.id),
                    "costline_id": str(line.id),
                    "action": "reclassify",
                    "ot_hours": "3",
                    "remaining_hours": "0",
                    "accounting_date": TUESDAY.isoformat(),
                    "job_name": shop_job.name,
                    "job_id": str(shop_job.id),
                    "unit_cost": "48.00",
                    "xero_ot": "3",
                    "jm_ot": "0",
                    "ot_gap": "3",
                }
            )

        with pytest.raises(CommandError, match="does not match"):
            _run("reclassify_overtime_entries", "--apply", str(csv_path))
        line.refresh_from_db()
        assert line.quantity == Decimal("8.000")


class TestCreateSpecialJob:
    """create_special_job: one special-status job on the shop company."""

    def test_creates_special_job_with_cost_sets(self) -> None:
        output = _run("create_special_job", "--name", "Overhead Things")

        assert "Created job 'Overhead Things'" in output
        job = Job.objects.get(name="Overhead Things")
        assert job.status == "special"
        assert job.company_id == CompanyDefaults.get_solo().shop_company_id
        assert job.default_xero_pay_item is not None
        assert job.default_xero_pay_item.name == "Ordinary Time"
        assert sorted(job.cost_sets.values_list("kind", flat=True)) == [
            "actual",
            "estimate",
            "quote",
        ]

    def test_dry_run_creates_nothing(self) -> None:
        output = _run("create_special_job", "--name", "Overhead Things", "--dry-run")

        assert "DRY RUN" in output
        assert not Job.objects.filter(name="Overhead Things").exists()

    def test_duplicate_name_is_refused(self, creator: Staff) -> None:
        _make_special_job("Overhead Things", creator)
        with pytest.raises(CommandError, match="already exists"):
            _run("create_special_job", "--name", "Overhead Things")

    def test_unknown_pay_item_is_refused(self) -> None:
        with pytest.raises(CommandError, match="not found"):
            _run("create_special_job", "--name", "Overhead Things", "--pay-item", "No Such Item")


class TestReassignTimeEntries:
    """reassign_time_entries: move lines to another staff member at their rate."""

    def test_reassigns_and_reprices_by_staff_and_date(self, creator: Staff) -> None:
        staff_a = make_staff("ra-a@example.com", first_name="Alpha", last_name="Worker")
        staff_b = make_staff(
            "ra-b@example.com",
            first_name="Bravo",
            last_name="Worker",
            base_wage_rate=Decimal("50.00"),
        )
        shop_job = _make_special_job("Shop Time", creator)
        line_one = _make_shop_time_line(shop_job, staff_a, accounting_date=TUESDAY)
        line_two = _make_shop_time_line(shop_job, staff_a, accounting_date=TUESDAY, hours="2.000")

        output = _run(
            "reassign_time_entries",
            "--from-staff",
            "Alpha",
            "--to-staff",
            "Bravo",
            "--date",
            TUESDAY.isoformat(),
        )

        assert "Done. Reassigned 2 entries" in output
        for line in (line_one, line_two):
            line.refresh_from_db()
            assert line.staff_id == staff_b.id
            assert line.unit_cost == Decimal("50.00")
            assert line.meta["staff_id"] == str(staff_b.id)

    def test_dry_run_changes_nothing(self, creator: Staff) -> None:
        staff_a = make_staff("ra-c@example.com", first_name="Charly", last_name="Worker")
        make_staff("ra-d@example.com", first_name="Deltas", last_name="Worker")
        shop_job = _make_special_job("Shop Time", creator)
        line = _make_shop_time_line(shop_job, staff_a, accounting_date=TUESDAY)

        output = _run(
            "reassign_time_entries",
            "--from-staff",
            "Charly",
            "--to-staff",
            "Deltas",
            "--date",
            TUESDAY.isoformat(),
            "--dry-run",
        )

        assert "DRY RUN" in output
        line.refresh_from_db()
        assert line.staff_id == staff_a.id

    def test_ambiguous_staff_name_is_refused(self) -> None:
        make_staff("ra-e@example.com", first_name="Brava", last_name="Worker")
        make_staff("ra-f@example.com", first_name="Bravado", last_name="Worker")
        with pytest.raises(CommandError, match="Multiple staff match"):
            _run(
                "reassign_time_entries",
                "--from-staff",
                "Brava",
                "--to-staff",
                "Brav",
                "--date",
                TUESDAY.isoformat(),
            )

    def test_no_matching_entries_is_refused(self) -> None:
        make_staff("ra-g@example.com", first_name="Golfer", last_name="Worker")
        make_staff("ra-h@example.com", first_name="Hotelo", last_name="Worker")
        with pytest.raises(CommandError, match="No matching time entries"):
            _run(
                "reassign_time_entries",
                "--from-staff",
                "Golfer",
                "--to-staff",
                "Hotelo",
                "--date",
                TUESDAY.isoformat(),
            )

    def test_missing_selection_is_refused(self) -> None:
        make_staff("ra-i@example.com", first_name="Indigo", last_name="Worker")
        with pytest.raises(CommandError, match="Specify either --ids"):
            _run("reassign_time_entries", "--to-staff", "Indigo")
