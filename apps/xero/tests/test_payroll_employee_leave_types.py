"""Employee leave eligibility at the Xero boundary."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.company.tests.conftest import make_company
from apps.core.models import CompanyDefaults
from apps.timesheet.tests.conftest import make_leave_job, make_staff
from apps.xero import payroll_employees, seeding
from apps.xero.models import XeroPayItem

pytestmark = pytest.mark.django_db

TENANT = "leave-ready-tenant"


def _configure_required_types() -> dict[str, str]:
    """The four Leave-API categories configured for TENANT, as name -> Xero id.

    Fable: Configuration goes through make_leave_job (the one leave-type
    builder); the only extra step is claiming the seeded pay-item catalogue
    for the tenant under test, because "configured" requires the pay item to
    belong to the connected organisation.
    """
    CompanyDefaults.objects.filter(id=1).update(xero_tenant_id=TENANT)
    CompanyDefaults.clear_cache()
    XeroPayItem.objects.filter(uses_leave_api=True).update(xero_tenant_id=TENANT)
    superuser = make_staff("leave-types-super@example.com", is_superuser=True, xero_user_id="")
    company = make_company("Leave Types Test Company")
    ids: dict[str, str] = {}
    for name in ("Annual Leave", "Sick Leave", "Unpaid Leave", "Bereavement Leave"):
        job = make_leave_job(company, superuser, name)
        pay_item = job.default_xero_pay_item
        assert pay_item is not None and pay_item.xero_id is not None
        ids[name] = pay_item.xero_id
    return ids


def _response(*ids: str) -> SimpleNamespace:
    return SimpleNamespace(
        leave_types=[SimpleNamespace(leave_type_id=leave_type_id) for leave_type_id in ids]
    )


def test_assigns_only_missing_non_accruing_types_and_verifies_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _configure_required_types()
    api = MagicMock()
    api.get_employee_leave_types.side_effect = [
        _response(ids["Annual Leave"], ids["Sick Leave"]),
        _response(*ids.values()),
    ]
    api.create_employee_leave_type.side_effect = lambda **kwargs: SimpleNamespace(
        leave_type=SimpleNamespace(leave_type_id=kwargs["employee_leave_type"].leave_type_id)
    )
    monkeypatch.setattr(payroll_employees, "get_tenant_id", lambda: TENANT)
    monkeypatch.setattr(payroll_employees, "get_api_client", object)
    monkeypatch.setattr(payroll_employees, "PayrollNzApi", lambda _client: api)

    assigned = payroll_employees.ensure_employee_leave_types("employee-1")

    assert assigned == set(ids.values())
    payloads = [
        call.kwargs["employee_leave_type"] for call in api.create_employee_leave_type.call_args_list
    ]
    assert {payload.leave_type_id for payload in payloads} == {
        ids["Unpaid Leave"],
        ids["Bereavement Leave"],
    }
    assert all(payload.schedule_of_accrual == "NoAccruals" for payload in payloads)
    assert all(payload.opening_balance == 0.0 for payload in payloads)


def test_missing_standard_leave_is_refused_instead_of_inventing_accruals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _configure_required_types()
    api = MagicMock()
    api.get_employee_leave_types.return_value = _response(ids["Annual Leave"])
    monkeypatch.setattr(payroll_employees, "get_tenant_id", lambda: TENANT)
    monkeypatch.setattr(payroll_employees, "get_api_client", object)
    monkeypatch.setattr(payroll_employees, "PayrollNzApi", lambda _client: api)

    with pytest.raises(ValueError, match="Sick Leave"):
        payroll_employees.ensure_employee_leave_types("employee-1")

    api.create_employee_leave_type.assert_not_called()


def test_required_mapping_must_belong_to_the_connected_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_required_types()
    XeroPayItem.objects.filter(name="Bereavement Leave", uses_leave_api=True).update(
        xero_tenant_id="another-tenant"
    )
    monkeypatch.setattr(payroll_employees, "get_tenant_id", lambda: TENANT)

    with pytest.raises(ValueError, match="Bereavement Leave"):
        payroll_employees.missing_employee_leave_types("employee-1")


def test_employee_seed_repairs_already_linked_staff(monkeypatch: pytest.MonkeyPatch) -> None:
    staff = make_staff("leave-repair@example.com")
    staff.xero_tenant_id = TENANT
    staff.xero_user_id = "11111111-1111-1111-1111-111111111111"
    staff.save(update_fields=["xero_tenant_id", "xero_user_id"])
    repaired: list[str] = []

    def _repair(employee_id: str) -> None:
        repaired.append(employee_id)

    monkeypatch.setattr(
        seeding, "missing_employee_leave_types", lambda _employee_id: ["Unpaid Leave"]
    )
    monkeypatch.setattr(seeding, "ensure_employee_leave_types", _repair)

    seeding._employees_phase(TENANT, dry_run=False, report=lambda _message: None)

    assert repaired == [str(staff.xero_user_id)]


def test_seed_convergence_counts_linked_staff_without_required_leave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    CompanyDefaults.objects.filter(id=1).update(test_company_name="Leave Test Company")
    make_company("Leave Test Company", xero_contact_id="contact-1", xero_tenant_id=TENANT)
    XeroPayItem.objects.update(xero_tenant_id=TENANT)
    staff = make_staff("leave-convergence@example.com")
    staff.xero_tenant_id = TENANT
    staff.xero_user_id = "22222222-2222-2222-2222-222222222222"
    staff.save(update_fields=["xero_tenant_id", "xero_user_id"])
    monkeypatch.setattr(
        seeding, "missing_employee_leave_types", lambda _employee_id: ["Bereavement Leave"]
    )

    assert seeding.seed_convergence(TENANT).staff_pending == 1
