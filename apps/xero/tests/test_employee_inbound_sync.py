"""Inbound payroll employees use the same atomic entity-sync contract."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from xero_python.payrollnz import Employee, PayrollNzApi

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.xero import payroll_employees
from apps.xero.payroll_employees import (
    PayBasis,
    PayrollEmployeeSnapshot,
    PayrollTermSnapshot,
    sync_employees,
)
from apps.xero.validation import XeroValidationError

pytestmark = pytest.mark.django_db


def test_known_immutable_demo_employee_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payroll_employees, "is_production_tenant", lambda _tenant: False)

    assert payroll_employees._demo_stub(
        cast("Employee", SimpleNamespace(first_name="Company", last_name="Director")),
        "demo-tenant",
    )


def snapshot(  # noqa: PLR0913 -- compact fixture factory exposes every payroll fact tests vary
    employee_id: str,
    email: str,
    *,
    first_name: str = "Ana",
    last_name: str = "Silva",
    pay_basis: PayBasis = "hourly",
    hourly_rate: Decimal | None = Decimal("31.25"),
) -> PayrollEmployeeSnapshot:
    return PayrollEmployeeSnapshot(
        tenant_id="tenant-1",
        employee_id=employee_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        start_date=date(2024, 2, 5),
        end_date=None,
        pay_basis=pay_basis,
        hourly_rate=hourly_rate,
        updated_date_utc=datetime(2026, 8, 18, 1, 2, tzinfo=UTC),
    )


def payroll_term(*, hourly_rate: Decimal = Decimal("31.25")) -> PayrollTermSnapshot:
    return PayrollTermSnapshot(
        effective_from=date(2024, 2, 5),
        pay_basis="hourly",
        annual_salary=None,
        hourly_rate=hourly_rate,
        working_weeks=[
            {
                "monday": 8,
                "tuesday": 8,
                "wednesday": 8,
                "thursday": 8,
                "friday": 8,
                "saturday": 0,
                "sunday": 0,
            }
        ],
        salary_wage_id="salary-1",
        working_pattern_id="pattern-1",
    )


def test_new_xero_employee_becomes_one_unusable_staff_login() -> None:
    sync_employees([snapshot("employee-1", "ana.payroll@example.com")])

    staff = Staff.objects.get(xero_user_id="employee-1")
    assert staff.office_email == "ana.payroll@example.com"
    assert staff.payroll_email == "ana.payroll@example.com"
    assert staff.has_usable_password() is False
    assert staff.employment_start_date == date(2024, 2, 5)
    assert staff.pay_basis == "hourly"
    assert staff.base_wage_rate == Decimal("31.25")
    assert staff.xero_fields_checksum is not None
    assert len(staff.xero_fields_checksum) == 64


def test_unchanged_employee_sync_does_not_write_staff_or_replace_terms() -> None:
    """The hourly full fetch is a database no-op when its complete projection is identical."""
    incoming = replace(
        snapshot("employee-1", "ana.payroll@example.com"),
        payroll_terms=(payroll_term(),),
    )
    sync_employees([incoming])
    staff = Staff.objects.get(xero_user_id="employee-1")
    original_staff_updated_at = staff.updated_at
    original_history_count = staff.history.count()
    original_term = StaffPayrollTerm.objects.get(staff=staff)

    sync_employees([incoming])

    staff.refresh_from_db()
    term = StaffPayrollTerm.objects.get(staff=staff)
    assert staff.updated_at == original_staff_updated_at
    assert staff.history.count() == original_history_count
    assert term.id == original_term.id
    assert term.updated_at == original_term.updated_at


def test_child_payroll_change_moves_checksum_without_parent_timestamp_change() -> None:
    """Salary and working-pattern resources have no Xero modified timestamp of their own."""
    original = replace(
        snapshot("employee-1", "ana.payroll@example.com"),
        payroll_terms=(payroll_term(),),
    )
    sync_employees([original])
    staff = Staff.objects.get(xero_user_id="employee-1")
    original_checksum = staff.xero_fields_checksum

    changed = replace(original, payroll_terms=(payroll_term(hourly_rate=Decimal("32.00")),))
    sync_employees([changed])

    staff.refresh_from_db()
    term = StaffPayrollTerm.objects.get(staff=staff)
    assert staff.xero_last_modified == original.updated_date_utc
    assert staff.xero_fields_checksum != original_checksum
    assert term.hourly_rate == Decimal("32.00")


def test_unchanged_remote_checksum_does_not_hide_local_xero_field_drift() -> None:
    """The stored digest is evidence of the last apply, not permission to trust local state."""
    incoming = snapshot("employee-1", "ana.payroll@example.com")
    sync_employees([incoming])
    staff = Staff.objects.get(xero_user_id="employee-1")
    original_checksum = staff.xero_fields_checksum
    Staff.objects.filter(pk=staff.pk).update(first_name="Drifted")

    sync_employees([incoming])

    staff.refresh_from_db()
    assert staff.first_name == "Ana"
    assert staff.xero_fields_checksum == original_checksum


def test_an_active_xero_employee_never_clears_a_recorded_departure() -> None:
    """Xero having no end date means nobody told Xero, not that they came back.

    Ending someone in Xero is a business process that needs a final pay run, so
    an employee who left months ago is still ACTIVE there with no ``end_date``
    until that run happens — ``payroll_employee_sync`` records that Xero does
    not persist ``Employee.end_date`` and NZ payroll exposes no termination
    endpoint at all. ``date_left`` is the DocketWorks judgement "I do not
    expect this person back", which is the earlier and different fact.

    Clearing it would put a departed employee back on the weekly grid, make
    them postable, and destroy the one signal the payroll reconciliation uses
    to report that Xero is still paying them.
    """
    staff = Staff.objects.create_user(
        office_email="departed@office.example",
        payroll_email="departed@payroll.example",
        password="secret",
        first_name="Dana",
        last_name="Parted",
    )
    staff.xero_user_id = "employee-9"
    staff.date_left = date(2026, 3, 6)
    staff.save(update_fields=["xero_user_id", "date_left"])

    sync_employees([snapshot("employee-9", "departed@payroll.example")])

    staff.refresh_from_db()
    assert staff.date_left == date(2026, 3, 6)
    synced_at = staff.updated_at

    sync_employees([snapshot("employee-9", "departed@payroll.example")])

    staff.refresh_from_db()
    assert staff.date_left == date(2026, 3, 6)
    assert staff.updated_at == synced_at


def test_a_xero_end_date_records_a_departure_we_did_not_have() -> None:
    """The one direction that flows: Xero terminated them and we had not noticed."""
    staff = Staff.objects.create_user(
        office_email="leaver@office.example",
        payroll_email="leaver@payroll.example",
        password="secret",
        first_name="Lee",
        last_name="Ver",
    )
    staff.xero_user_id = "employee-8"
    staff.save(update_fields=["xero_user_id"])

    terminated = snapshot("employee-8", "leaver@payroll.example")
    sync_employees([replace(terminated, end_date=date(2026, 5, 15))])

    staff.refresh_from_db()
    assert staff.date_left == date(2026, 5, 15)


def test_existing_staff_keeps_docketworks_owned_fields() -> None:
    staff = Staff.objects.create_user(
        office_email="ana@office.example",
        payroll_email="old-payroll@example.com",
        password="secret",
        first_name="Old",
        last_name="Name",
        preferred_name="Annie",
        is_office_staff=True,
    )
    original_password = staff.password

    sync_employees(
        [
            snapshot(
                "employee-1",
                "old-payroll@example.com",
                first_name="Ana",
                last_name="Silva",
            )
        ]
    )

    staff.refresh_from_db()
    assert staff.office_email == "ana@office.example"
    assert staff.preferred_name == "Annie"
    assert staff.is_office_staff is True
    assert staff.password == original_password
    assert staff.first_name == "Ana"
    assert staff.last_name == "Silva"
    assert staff.xero_user_id == "employee-1"


def test_salary_is_imported_but_has_no_hourly_cost_rate() -> None:
    sync_employees(
        [
            snapshot(
                "employee-1",
                "salary@example.com",
                pay_basis="salary",
                hourly_rate=None,
            )
        ]
    )

    staff = Staff.objects.get(xero_user_id="employee-1")
    assert staff.pay_basis == "salary"
    assert staff.base_wage_rate == Decimal("0")


def test_salary_and_working_pattern_history_are_imported_as_effective_terms() -> None:
    term = PayrollTermSnapshot(
        effective_from=date(2026, 7, 1),
        pay_basis="salary",
        annual_salary=Decimal("104000.00"),
        hourly_rate=None,
        working_weeks=[
            {
                "monday": 8,
                "tuesday": 8,
                "wednesday": 8,
                "thursday": 8,
                "friday": 8,
                "saturday": 0,
                "sunday": 0,
            }
        ],
        salary_wage_id="salary-1",
        working_pattern_id="pattern-1",
    )
    sync_employees(
        [
            replace(
                snapshot(
                    "employee-1",
                    "salary@example.com",
                    pay_basis="salary",
                    hourly_rate=None,
                ),
                payroll_terms=(term,),
            )
        ]
    )

    stored = StaffPayrollTerm.objects.get(staff__xero_user_id="employee-1")
    assert stored.effective_from == date(2026, 7, 1)
    assert stored.annual_salary == Decimal("104000.00")
    assert stored.working_weeks[0]["monday"] == 8
    assert stored.xero_working_pattern_id == "pattern-1"


def test_ambiguous_batch_aborts_before_creating_any_staff() -> None:
    with pytest.raises(ValueError, match="Multiple Xero employees use payroll email"):
        sync_employees(
            [
                snapshot("employee-1", "same@example.com"),
                snapshot("employee-2", "same@example.com"),
            ]
        )

    assert not Staff.objects.filter(xero_tenant_id="tenant-1").exists()


def test_invalid_employee_email_aborts_before_the_sync_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee = cast(
        "Employee",
        SimpleNamespace(
            employee_id="employee-2",
            first_name="Bad",
            last_name="Email",
            email="not-an-email",
            start_date=date(2024, 2, 5),
            end_date=None,
            updated_date_utc=datetime(2026, 8, 18, 1, 2, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(
        payroll_employees,
        "_salary_and_wages",
        lambda *_args: [
            SimpleNamespace(
                effective_from=date(2024, 2, 5),
                status="ACTIVE",
                payment_type="HOURLY",
                rate_per_unit=31.25,
                annual_salary=None,
            )
        ],
    )

    with pytest.raises(XeroValidationError):
        payroll_employees._snapshot(
            cast("PayrollNzApi", MagicMock()),
            "tenant-1",
            employee,
        )

    assert not Staff.objects.filter(xero_tenant_id="tenant-1").exists()
