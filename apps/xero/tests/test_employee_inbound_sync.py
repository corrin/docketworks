"""Inbound payroll employees use the same atomic entity-sync contract."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from xero_python.payrollnz import Employee, PayrollNzApi

from apps.accounts.models import Staff
from apps.xero import payroll_employees
from apps.xero.payroll_employees import PayBasis, PayrollEmployeeSnapshot, sync_employees
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


def test_new_xero_employee_becomes_one_unusable_staff_login() -> None:
    sync_employees([snapshot("employee-1", "ana.payroll@example.com")])

    staff = Staff.objects.get(xero_user_id="employee-1")
    assert staff.office_email == "ana.payroll@example.com"
    assert staff.payroll_email == "ana.payroll@example.com"
    assert staff.has_usable_password() is False
    assert staff.employment_start_date == date(2024, 2, 5)
    assert staff.pay_basis == "hourly"
    assert staff.base_wage_rate == Decimal("31.25")


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
