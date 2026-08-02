"""Tests for the Staff <-> Xero Payroll employee matching engine.

Only the non-Xero half of v1's ``PayrollEmployeeSyncService`` is ported, so the
tests exercise it directly with plain stand-ins rather than a mocked Xero SDK
(v1's own tests mocked six API functions to reach the same three rules).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.timesheet.services import payroll_employee_sync as sync
from apps.timesheet.tests.conftest import make_staff

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class FakeEmployee:
    """Stand-in for a Xero Payroll NZ employee (only the matched fields)."""

    employee_id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    job_title: str | None = None


class TestSerializeEmployee:
    def test_extracts_the_staff_uuid_from_the_job_title(self) -> None:
        staff_id = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        record = sync.serialize_employee(
            FakeEmployee("emp-1", job_title=f"Workshop Worker [{staff_id.upper()}]")
        )

        assert record.staff_id == staff_id

    def test_normalises_names_and_email(self) -> None:
        record = sync.serialize_employee(
            FakeEmployee("emp-1", first_name="  Ana ", last_name=" Silva", email=" A@B.COM ")
        )

        assert record.first_name == "Ana"
        assert record.last_name == "Silva"
        assert record.email == "a@b.com"

    def test_absent_fields_become_empty_or_none(self) -> None:
        record = sync.serialize_employee(FakeEmployee("emp-1"))

        assert record.first_name == ""
        assert record.email is None
        assert record.staff_id is None


@pytest.mark.usefixtures("company")
class TestMatching:
    def _staff(self) -> Staff:
        return make_staff("match-target@example.com", first_name="Ana", last_name="Silva")

    def test_uuid_in_the_job_title_beats_email_and_name(self) -> None:
        """The UUID is the only key that survives a database restore."""
        staff = self._staff()
        by_uuid = FakeEmployee("emp-uuid", job_title=f"Workshop Worker [{staff.id}]")
        by_email = FakeEmployee("emp-email", email=staff.email)
        index = sync.index_employees([by_email, by_uuid])

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-uuid"

    def test_email_beats_name(self) -> None:
        staff = self._staff()
        index = sync.index_employees(
            [
                FakeEmployee("emp-name", first_name="Ana", last_name="Silva"),
                FakeEmployee("emp-email", email=staff.email.upper()),
            ]
        )

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-email"

    def test_name_is_the_last_resort(self) -> None:
        staff = self._staff()
        index = sync.index_employees(
            [FakeEmployee("emp-name", first_name="ANA", last_name="silva")]
        )

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-name"

    def test_no_match_returns_none(self) -> None:
        staff = self._staff()
        index = sync.index_employees([FakeEmployee("emp-other", first_name="Bo", last_name="Kim")])

        assert sync.match_staff_to_employee(staff, index) is None

    def test_the_first_employee_wins_a_duplicated_key(self) -> None:
        staff = self._staff()
        index = sync.index_employees(
            [
                FakeEmployee("emp-first", email=staff.email),
                FakeEmployee("emp-second", email=staff.email),
            ]
        )

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-first"


@pytest.mark.usefixtures("company")
class TestSummaries:
    def test_link_summary_carries_both_sides(self) -> None:
        staff = make_staff("summary@example.com", first_name="Ana", last_name="Silva")
        record = sync.serialize_employee(
            FakeEmployee("emp-1", first_name="Ana", last_name="Silva", email="ana@xero.test")
        )

        summary = sync.link_summary(staff, "emp-1", record)

        assert summary["staff_id"] == str(staff.id)
        assert summary["email"] == "summary@example.com"
        assert summary["xero_employee_id"] == "emp-1"
        assert summary["xero_email"] == "ana@xero.test"
        assert summary["xero_name"] == "Ana Silva"

    def test_link_summary_without_a_match(self) -> None:
        staff = make_staff("unmatched@example.com")

        summary = sync.link_summary(staff, None, None)

        assert summary["xero_employee_id"] is None
        assert summary["xero_name"] is None


@pytest.mark.usefixtures("company")
class TestStaffFacts:
    def test_job_title_carries_the_uuid_for_relinking(self) -> None:
        staff = make_staff("title@example.com")

        assert sync.xero_job_title(staff) == f"Workshop Worker [{staff.id}]"

    def test_hours_per_week_reads_the_staff_row(self) -> None:
        staff = make_staff("hours@example.com")
        staff.hours_fri = Decimal("6.00")
        staff.save(update_fields=["hours_fri", "updated_at"])

        assert sync.hours_per_week(staff) == {
            "monday": 8.0,
            "tuesday": 8.0,
            "wednesday": 8.0,
            "thursday": 8.0,
            "friday": 6.0,
            "saturday": 0.0,
            "sunday": 0.0,
        }

    def test_link_staff_records_the_employee_id(self) -> None:
        staff = make_staff("link@example.com")

        sync.link_staff(staff, "emp-42")

        staff.refresh_from_db()
        assert staff.xero_user_id == "emp-42"

    def test_syncable_staff_excludes_leavers_and_unpaid_logins(self) -> None:
        payable = make_staff("payable@example.com")
        make_staff("unpaid@example.com", base_wage_rate=Decimal("0.00"))
        leaver = make_staff("gone@example.com")
        leaver.date_left = date(2026, 1, 1)
        leaver.save(update_fields=["date_left", "updated_at"])

        assert [staff.id for staff in sync.syncable_staff()] == [payable.id]

    def test_clean_string_trims_and_truncates(self) -> None:
        assert sync.clean_string("  Ana  ") == "Ana"
        assert sync.clean_string("   ") is None
        assert sync.clean_string(None) is None
        assert sync.clean_string("abcdef", 3) == "abc"

    def test_active_on_uses_the_end_date(self) -> None:
        today = date(2026, 5, 4)
        assert sync.active_on(None, today) is True
        assert sync.active_on(date(2026, 6, 1), today) is True
        assert sync.active_on(date(2026, 5, 4), today) is False


@pytest.mark.usefixtures("company")
class TestDefaultWorkingHours:
    def test_derived_from_the_company_working_times(self) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.fri_end = "12:00"
        defaults.save(update_fields=["fri_end"])

        hours = sync.default_working_hours()

        assert hours["monday"] == 8.0  # 07:00 - 15:00
        assert hours["friday"] == 5.0  # 07:00 - 12:00
        assert hours["saturday"] == 0.0


class TestPhase4Seams:
    def test_sync_staff_is_a_seam(self) -> None:
        with pytest.raises(NotImplementedError, match="Phase 4"):
            sync.sync_staff()

    def test_import_staff_from_xero_is_a_seam(self) -> None:
        with pytest.raises(NotImplementedError, match="Phase 4"):
            sync.import_staff_from_xero(initial_password="irrelevant")
