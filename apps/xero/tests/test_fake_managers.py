"""Under XERO_FAKE the application's managers and syncs run unchanged against the fake (ADR 0060).

Business risk covered: the fake is only worth anything if the code an E2E
run drives — the invoice manager, the company create service, the employee
sync, the cleanup — reaches it through the real registry, the real
provider and the real SDK, and persists what it answers exactly as it would
persist Xero's answer. A fake that only worked when called directly would
prove nothing about the run.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounting.registry import get_provider
from apps.accounts.models import Staff, StaffPayrollTerm
from apps.company.models import Company
from apps.company.services.company_rest_service import CompanyRestService, DuplicateContactError
from apps.company.tests.job_fixtures import make_material_line
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.constants import TENANT_ID_CACHE_KEY, tenant_cache
from apps.xero.documents.invoice import XeroInvoiceManager
from apps.xero.fake.rest_client import FakeXeroRESTClient
from apps.xero.fake.seed import (
    seed_contacts,
    seed_payroll,
)
from apps.xero.fake.store import FakeXeroStore, Kind
from apps.xero.fake.testing import CALENDAR_ID, connected_to_the_fake
from apps.xero.models import XeroAccount
from apps.xero.payroll_employees import (
    _current_employee_projection,
    _incoming_employee_projection,
    _xero_fields_checksum,
    get_employees_for_sync,
)
from apps.xero.provider import XeroAccountingProvider
from apps.xero.tests.conftest import TEST_TENANT_ID

pytestmark = pytest.mark.django_db


@pytest.fixture
def fake_xero() -> Iterator[FakeXeroStore]:
    """The process pointed at the fake: flag set, a connected app row, the fixtures seeded."""
    with connected_to_the_fake(TEST_TENANT_ID) as store:
        yield store


@pytest.fixture
def company(fake_xero: FakeXeroStore) -> Company:
    created = Company.objects.create(
        name="[TEST] Managers Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_last_modified=timezone.now(),
    )
    seed_contacts(fake_xero)
    return created


def test_the_transport_under_the_flag_is_the_fake_and_the_provider_is_the_real_one(
    fake_xero: FakeXeroStore,
) -> None:
    del fake_xero

    assert isinstance(get_api_client().rest_client, FakeXeroRESTClient)
    assert type(get_provider()) is XeroAccountingProvider


def test_the_invoice_manager_persists_the_fake_s_totals_and_number(
    fake_xero: FakeXeroStore, company: Company, office_staff: Staff
) -> None:
    XeroAccount.objects.create(
        xero_id=uuid.uuid4(),
        account_code="200",
        account_name="Sales",
        xero_last_modified=timezone.now(),
        raw_json={},
    )
    job = Job(company=company, name="Managers Job", pricing_methodology="fixed_price")
    job.save(staff=office_staff)
    make_material_line(job, set_kind="quote", rev="1000.00", cost="0.00")

    with patch.object(XeroInvoiceManager, "_attach_workshop_pdf", return_value=None):
        result = XeroInvoiceManager(company=company, job=job, staff=office_staff).create_document(
            total_amount=Decimal("1000.00"),
            billing_metadata={
                "mode": "invoice_full",
                "target_basis": "quote",
                "target_total": "1000.00",
                "prior_invoiced_total": "0.00",
                "calculated_amount": "1000.00",
            },
        )

    assert result["success"], result
    invoice = job.invoices.get()
    assert invoice.number == "INV-0001"
    assert invoice.total_excl_tax == Decimal("1000.00")
    assert invoice.tax == Decimal("150.00")
    assert invoice.total_incl_tax == Decimal("1150.00")
    assert fake_xero.get(Kind.INVOICE, str(invoice.xero_id)) is not None
    assert fake_xero.listing(Kind.HISTORY_RECORD, parent_id=str(invoice.xero_id)).count() == 1


def test_company_create_pushes_a_contact_the_fake_then_holds(fake_xero: FakeXeroStore) -> None:
    created = CompanyRestService.create_company(
        {"name": "[TEST] Pushed Co", "is_account_customer": True, "allow_jobs": True}
    )
    assert created.xero_contact_id
    held = fake_xero.get(Kind.CONTACT, created.xero_contact_id)
    assert held is not None and held.name == "[TEST] Pushed Co"
    with pytest.raises(DuplicateContactError):
        CompanyRestService.create_company(
            {"name": "[TEST] Pushed Co", "is_account_customer": True, "allow_jobs": True}
        )


def test_the_employee_sync_sees_the_seeded_staff_as_unchanged(fake_xero: FakeXeroStore) -> None:
    staff = Staff.objects.create_user(
        "ada@example.test",
        "x",
        first_name="Ada",
        last_name="Lovelace",
        payroll_email="ada@example.test",
        employment_start_date=date(2025, 4, 1),
        pay_basis="hourly",
        base_wage_rate=Decimal("36.05"),
        xero_tenant_id=TEST_TENANT_ID,
        xero_last_modified=datetime(2026, 9, 12, 3, 49, 26, tzinfo=UTC),
    )
    staff.xero_user_id = str(uuid.uuid4())
    staff.save(update_fields=["xero_user_id"])
    StaffPayrollTerm.objects.create(
        staff=staff,
        effective_from=date(2025, 4, 1),
        pay_basis="hourly",
        hourly_rate=Decimal("36.05"),
        working_weeks=[
            {
                "monday": 8.0,
                "tuesday": 8.0,
                "wednesday": 8.0,
                "thursday": 8.0,
                "friday": 8.0,
                "saturday": 0.0,
                "sunday": 0.0,
            }
        ],
        xero_salary_wage_id=str(uuid.uuid4()),
        xero_working_pattern_id=str(uuid.uuid4()),
    )
    seed_payroll(fake_xero, CALENDAR_ID)

    batch = get_employees_for_sync(
        xero_tenant_id=TEST_TENANT_ID, if_modified_since="", refresh_details=True
    )

    assert [snapshot.employee_id for snapshot in batch.employees] == [staff.xero_user_id]
    incoming = _incoming_employee_projection(
        batch.employees[0],
        current_date_left=staff.date_left,
        loading=CompanyDefaults.get_solo().labour_cost_loading,
    )
    staff.refresh_from_db()
    assert _xero_fields_checksum(incoming) == _xero_fields_checksum(
        _current_employee_projection(staff)
    )


def test_connecting_to_the_fake_forgets_a_tenant_cached_by_an_earlier_test() -> None:
    """The tenant id is cached per process; a stale one sends writes to another store.

    CI, 2026-09-13: a test earlier in the same worker left its tenant in the
    cache, the cleanup test then created its invoice under that tenant and
    looked for it under the fake's, and the fake answered 404.
    """
    tenant_cache().set(TENANT_ID_CACHE_KEY, "tenant-left-by-an-earlier-test")
    with connected_to_the_fake(TEST_TENANT_ID):
        assert get_tenant_id() == TEST_TENANT_ID
    assert tenant_cache().get(TENANT_ID_CACHE_KEY) is None, "the fake's tenant outlived its block"
