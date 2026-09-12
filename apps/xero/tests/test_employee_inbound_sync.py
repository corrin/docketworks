"""Inbound payroll employees use the same atomic entity-sync contract."""

import time
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from django.conf import settings
from django.utils import timezone
from xero_python.payrollnz import Employee, PayrollNzApi

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.accounts.services.payroll_terms import salary_cost_rate
from apps.core.models import CompanyDefaults
from apps.job.models import CostLine, Job
from apps.timesheet.services.workshop_timesheet_service import WorkshopEntryCreateData, create_entry
from apps.xero import payroll_employees
from apps.xero import sync as sync_engine
from apps.xero.models import XeroDetailRefresh
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


def test_a_rate_finer_than_the_column_still_reaches_a_no_op() -> None:
    """Xero quotes rates to four decimals and the columns hold two.

    Rounding only at the database leaves the incoming and stored projections
    permanently unequal, so these employees are rewritten — with a fresh payroll
    term history row — on every hourly sync forever.
    """
    incoming = replace(
        snapshot("employee-1", "ana.payroll@example.com", hourly_rate=Decimal("24.0385")),
        payroll_terms=(payroll_term(hourly_rate=Decimal("24.0385")),),
    )
    sync_employees([incoming])
    staff = Staff.objects.get(xero_user_id="employee-1")
    original_staff_updated_at = staff.updated_at
    original_history_count = staff.history.count()
    original_term = StaffPayrollTerm.objects.get(staff=staff)

    sync_employees([incoming])

    staff.refresh_from_db()
    term = StaffPayrollTerm.objects.get(staff=staff)
    assert staff.base_wage_rate == Decimal("24.04")
    assert staff.updated_at == original_staff_updated_at
    assert staff.history.count() == original_history_count
    assert term.id == original_term.id


def test_a_wage_rate_written_from_a_stale_loading_is_re_derived() -> None:
    """The skip must not make the KAN-350 damage permanent.

    wage_rate is derived from base_wage_rate and the labour cost loading, so a
    rate that no longer matches that product is drift the sync owns — exactly
    the state the stale-singleton save left behind.
    """
    incoming = snapshot("employee-1", "ana.payroll@example.com")
    sync_employees([incoming])
    staff = Staff.objects.get(xero_user_id="employee-1")
    correct_wage_rate = staff.wage_rate
    # update() bypasses Staff.save()'s recompute, which is what makes this a
    # faithful reproduction: the incident wrote wage_rate directly too.
    Staff.objects.filter(pk=staff.pk).update(wage_rate=Decimal("1.23"))

    sync_employees([incoming])

    staff.refresh_from_db()
    assert staff.wage_rate == correct_wage_rate


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


@pytest.fixture
def employee_api(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The three payroll detail resources behind one list employee."""
    api = MagicMock()
    api.get_employees.return_value = SimpleNamespace(
        employees=[
            SimpleNamespace(
                employee_id="employee-1",
                first_name="Ana",
                last_name="Silva",
                email="ana.payroll@example.com",
                start_date=date(2024, 2, 5),
                end_date=None,
                updated_date_utc=datetime(2026, 8, 18, 1, 2, tzinfo=UTC),
            )
        ],
        pagination=SimpleNamespace(page_count=1),
    )
    api.get_employee_salary_and_wages.return_value = SimpleNamespace(
        salary_and_wages=[
            SimpleNamespace(
                effective_from=date(2024, 2, 5),
                status="ACTIVE",
                payment_type="Hourly",
                rate_per_unit=31.25,
                annual_salary=None,
                salary_and_wages_id="salary-1",
            )
        ],
        pagination=SimpleNamespace(page_count=1),
    )
    api.get_employee_working_patterns.return_value = SimpleNamespace(
        payee_working_patterns=[SimpleNamespace(payee_working_pattern_id="pattern-1")]
    )
    api.get_employee_working_pattern.return_value = SimpleNamespace(
        payee_working_pattern=SimpleNamespace(
            effective_from=date(2024, 2, 5),
            working_weeks=[SimpleNamespace(**payroll_term().working_weeks[0])],
        )
    )
    monkeypatch.setattr(payroll_employees, "PayrollNzApi", lambda _client: api)
    monkeypatch.setattr(payroll_employees, "get_api_client", lambda: None)
    return api


def test_eighteen_unchanged_employees_need_one_list_call(employee_api: MagicMock) -> None:
    employee_api.get_employees.return_value.employees = [
        SimpleNamespace(
            employee_id=f"employee-{n}",
            first_name="Ana",
            last_name=f"Silva{n}",
            email=f"ana{n}@example.com",
            start_date=date(2024, 2, 5),
            end_date=None,
            updated_date_utc=datetime(2026, 8, 18, 1, 2, tzinfo=UTC),
        )
        for n in range(18)
    ]
    first = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1", if_modified_since=""
    )
    assert len(employee_api.mock_calls) == 55
    sync_employees(first.employees)
    identities = set(StaffPayrollTerm.objects.values_list("id", flat=True))
    employee_api.reset_mock()

    second = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1", if_modified_since=""
    )
    sync_employees(second.employees)

    assert len(employee_api.mock_calls) == 1
    assert set(StaffPayrollTerm.objects.values_list("id", flat=True)) == identities


@pytest.mark.parametrize("damage", ["missing", "rate", "pattern", "derived", "loading", "metadata"])
def test_only_damaged_source_history_requires_detail_reads(
    employee_api: MagicMock,
    damage: str,
) -> None:

    incoming = replace(
        snapshot("employee-1", "ana.payroll@example.com"), payroll_terms=(payroll_term(),)
    )
    sync_employees([incoming])
    staff = Staff.objects.get(xero_user_id="employee-1")
    term_id = staff.payroll_terms.get().id
    if damage == "missing":
        staff.payroll_terms.all().delete()
    elif damage == "rate":
        staff.payroll_terms.update(hourly_rate=Decimal("1"))
    elif damage == "pattern":
        staff.payroll_terms.update(working_weeks=[])
    elif damage == "derived":
        Staff.objects.filter(pk=staff.pk).update(base_wage_rate=1, wage_rate=1, pay_basis="salary")
    elif damage == "loading":
        defaults = CompanyDefaults.get_solo()
        defaults.labour_cost_loading = Decimal("75")
        defaults.save(update_fields=["labour_cost_loading"])
    else:
        employee_api.get_employees.return_value.employees[0].first_name = "Anna"
    fetched = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1", if_modified_since=""
    )
    sync_employees(fetched.employees)
    staff.refresh_from_db()

    assert len(employee_api.mock_calls) == (4 if damage in {"missing", "rate", "pattern"} else 1)
    assert staff.base_wage_rate == Decimal("31.25")
    if damage in {"derived", "loading", "metadata"}:
        assert staff.payroll_terms.get().id == term_id
    if damage == "loading":
        assert staff.wage_rate == Decimal("54.69")
    if damage == "metadata":
        assert staff.first_name == "Anna"


def test_explicit_details_import_changed_pay_with_unchanged_employee_timestamp(
    employee_api: MagicMock,
) -> None:
    original = replace(
        snapshot("employee-1", "ana.payroll@example.com"), payroll_terms=(payroll_term(),)
    )
    sync_employees([original])
    employee_api.get_employee_salary_and_wages.return_value.salary_and_wages[
        0
    ].rate_per_unit = 37.51

    fetched = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1",
        if_modified_since="",
        refresh_details=True,
    )
    sync_employees(fetched.employees, detail_refresh_tenant_id="tenant-1")

    staff = Staff.objects.get(xero_user_id="employee-1")
    assert staff.base_wage_rate == Decimal("37.51")
    assert staff.xero_last_modified == original.updated_date_utc
    assert len(employee_api.mock_calls) == 4


def test_future_terms_activate_locally_without_replacing_history(
    employee_api: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future = replace(payroll_term(hourly_rate=Decimal("42")), effective_from=date(2026, 10, 1))
    sync_employees(
        [
            replace(
                snapshot("employee-1", "ana.payroll@example.com"),
                payroll_terms=(payroll_term(), future),
            )
        ]
    )
    identities = set(StaffPayrollTerm.objects.values_list("id", flat=True))
    monkeypatch.setattr(timezone, "localdate", lambda: date(2026, 10, 2))

    fetched = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1", if_modified_since=""
    )
    sync_employees(fetched.employees)

    assert Staff.objects.get(xero_user_id="employee-1").base_wage_rate == Decimal("42")
    assert len(employee_api.mock_calls) == 1
    assert set(StaffPayrollTerm.objects.values_list("id", flat=True)) == identities


@pytest.mark.parametrize("scheduled", [False, True])
def test_detail_job_uses_employee_engine_and_commits_success(
    employee_api: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    scheduled: bool,
) -> None:

    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(sync_engine, "get_valid_token", lambda: {"access_token": "test"})
    monkeypatch.setattr(sync_engine, "get_tenant_id", lambda: "tenant-1")
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    before = timezone.now()
    events = list(sync_engine.synchronise_xero_data(detail_refresh=True, only_if_due=scheduled))

    assert {event["entity"] for event in events} == {"employees"}
    assert events[-1]["status"] == "Completed"
    assert XeroDetailRefresh.objects.get(tenant_id="tenant-1").last_success_at >= before
    assert len(employee_api.mock_calls) == 4


def test_detail_success_is_atomic_with_employee_batch(monkeypatch: pytest.MonkeyPatch) -> None:

    prior = timezone.now()
    XeroDetailRefresh.objects.create(tenant_id="tenant-1", last_success_at=prior)
    first = replace(
        snapshot("employee-1", "ana.payroll@example.com"), payroll_terms=(payroll_term(),)
    )
    second = replace(first, employee_id="employee-2", email="bea@example.com")
    apply = payroll_employees._apply_employee_change

    def fail_second(
        incoming: PayrollEmployeeSnapshot,
        staff: Staff | None,
        tenant: str,
        checksum: str,
    ) -> Staff:
        if incoming.employee_id == "employee-2":
            raise RuntimeError("second employee failed")
        return apply(incoming, staff, tenant, checksum)

    monkeypatch.setattr(payroll_employees, "_apply_employee_change", fail_second)
    with pytest.raises(RuntimeError, match="second employee failed"):
        sync_employees([first, second], detail_refresh_tenant_id="tenant-1")

    assert not Staff.objects.filter(xero_tenant_id="tenant-1").exists()
    assert XeroDetailRefresh.objects.get(tenant_id="tenant-1").last_success_at == prior


def test_unchanged_and_empty_complete_batches_record_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    incoming = replace(
        snapshot("employee-1", "ana.payroll@example.com"), payroll_terms=(payroll_term(),)
    )
    sync_employees([incoming], detail_refresh_tenant_id="tenant-1")
    old = XeroDetailRefresh.objects.get(tenant_id="tenant-1").last_success_at
    later = old.replace(year=old.year + 1)
    monkeypatch.setattr(timezone, "now", lambda: later)
    term_id = StaffPayrollTerm.objects.get(staff__xero_user_id="employee-1").id
    sync_employees([incoming], detail_refresh_tenant_id="tenant-1")
    sync_employees([], detail_refresh_tenant_id="empty-tenant")

    assert XeroDetailRefresh.objects.get(tenant_id="tenant-1").last_success_at == later
    assert XeroDetailRefresh.objects.get(tenant_id="empty-tenant").last_success_at == later
    assert StaffPayrollTerm.objects.get(staff__xero_user_id="employee-1").id == term_id


def test_paged_pay_history_retains_future_salary_and_uses_working_hours(
    employee_api: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    CompanyDefaults.objects.update(labour_cost_loading=Decimal("20"))
    first_page = employee_api.get_employee_salary_and_wages.return_value
    first_page.pagination.page_count = 2
    second_page = SimpleNamespace(
        salary_and_wages=[
            SimpleNamespace(
                effective_from=date(2026, 10, 1),
                status="ACTIVE",
                payment_type="Salary",
                rate_per_unit=None,
                annual_salary=104000,
                salary_and_wages_id="salary-2",
            )
        ],
        pagination=SimpleNamespace(page_count=2),
    )
    employee_api.get_employee_salary_and_wages.side_effect = [first_page, second_page]
    monkeypatch.setattr(timezone, "localdate", lambda: date(2026, 9, 9))
    fetched = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1", if_modified_since=""
    )
    sync_employees(fetched.employees)
    assert len(fetched.employees[0].payroll_terms) == 2
    employee_api.reset_mock()
    monkeypatch.setattr(timezone, "localdate", lambda: date(2026, 10, 2))

    fetched = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1", if_modified_since=""
    )
    sync_employees(fetched.employees)
    staff = Staff.objects.get(xero_user_id="employee-1")
    assert staff.pay_basis == "salary"
    assert staff.base_wage_rate == 0
    assert salary_cost_rate(staff.payroll_terms.get(effective_from=date(2026, 10, 1))) == Decimal(
        "60"
    )
    assert len(employee_api.mock_calls) == 1


def test_imported_rate_prices_new_time_without_repricing_existing_lines(
    employee_api: MagicMock,
    job: "Job",
) -> None:

    CompanyDefaults.objects.update(labour_cost_loading=Decimal("20"))
    incoming = replace(
        snapshot("employee-1", "ana.payroll@example.com"), payroll_terms=(payroll_term(),)
    )
    sync_employees([incoming])
    staff = Staff.objects.get(xero_user_id="employee-1")
    payload: WorkshopEntryCreateData = {
        "job_id": job.id,
        "accounting_date": date(2026, 9, 9),
        "hours": Decimal("1"),
    }
    old = create_entry(staff, payload)
    assert CostLine.objects.get(pk=old["id"]).unit_cost == Decimal("37.50")
    pay = employee_api.get_employee_salary_and_wages.return_value.salary_and_wages[0]
    pay.rate_per_unit = 40
    fetched = payroll_employees.get_employees_for_sync(
        xero_tenant_id="tenant-1",
        if_modified_since="",
        refresh_details=True,
    )
    sync_employees(fetched.employees)
    staff.refresh_from_db()
    new = create_entry(staff, payload)

    assert CostLine.objects.get(pk=new["id"]).unit_cost == Decimal("48")
    assert CostLine.objects.get(pk=old["id"]).unit_cost == Decimal("37.50")


def test_hourly_sync_catches_up_after_a_failed_detail_refresh(
    employee_api: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(sync_engine, "get_valid_token", lambda: {"access_token": "test"})
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    employee_api.get_employee_working_pattern.side_effect = RuntimeError("Xero unavailable")
    with pytest.raises(RuntimeError, match="Xero unavailable"):
        list(sync_engine.sync_all_xero_data(entities=["employees"], xero_tenant_id="tenant-1"))
    assert not XeroDetailRefresh.objects.filter(tenant_id="tenant-1").exists()
    assert not Staff.objects.filter(xero_tenant_id="tenant-1").exists()

    employee_api.get_employee_working_pattern.side_effect = None
    employee_api.reset_mock()
    list(sync_engine.sync_all_xero_data(entities=["employees"], xero_tenant_id="tenant-1"))
    success = XeroDetailRefresh.objects.get(tenant_id="tenant-1").last_success_at
    assert len(employee_api.mock_calls) == 4
    employee_api.reset_mock()
    list(sync_engine.sync_all_xero_data(entities=["employees"], xero_tenant_id="tenant-1"))
    assert len(employee_api.mock_calls) == 1
    assert XeroDetailRefresh.objects.get(tenant_id="tenant-1").last_success_at == success
