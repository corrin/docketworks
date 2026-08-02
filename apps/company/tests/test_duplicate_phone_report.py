"""Tests for the duplicate-phones data-quality report and its endpoint (v1 port)."""

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.duplicate_phone_report import DuplicatePhoneReportService
from apps.company.tests.conftest import authenticate, make_company
from apps.crm.models import PhoneEndpoint

pytestmark = pytest.mark.django_db


def _phone(
    value: str,
    company: Company | None = None,
    contact: CompanyPersonLink | None = None,
) -> ContactMethod:
    """Insert a phone method bypassing the save() guard (legacy-style data)."""
    method = ContactMethod(
        company=company,
        person=contact.person if contact else None,
        method_type=ContactMethod.MethodType.PHONE,
        value=value,
    )
    method.normalized_value = ContactMethod.normalize_phone(value)
    ContactMethod.objects.bulk_create([method])
    return method


def _link(company: Company, name: str) -> CompanyPersonLink:
    person = Person.objects.create(name=name)
    return CompanyPersonLink.objects.create(company=company, person=person)


def test_detects_cross_company_number() -> None:
    acme = make_company("Acme Ltd")
    beta = make_company("Beta Ltd")
    _phone("021 111 111", company=acme)
    _phone("021 111 111", company=beta)

    report = DuplicatePhoneReportService().get_report()

    cross = [i for i in report["duplicate_phones"] if i["issue"] == "cross_company"]
    assert len(cross) == 1
    assert cross[0]["normalized_value"] == ContactMethod.normalize_phone("021 111 111")
    assert len(cross[0]["owners"]) == 2
    assert report["summary"]["cross_company"] == 1


def test_detects_internal_line_collision() -> None:
    company = make_company("Acme Ltd")
    contact = _link(company, "Paul Jones")
    _phone("09 636 5131", contact=contact)
    # Bypass PhoneEndpoint.save()'s collision guard (legacy-style data):
    # the report exists precisely to surface rows that predate the guard.
    endpoint = PhoneEndpoint(
        number="09 636 5131",
        label="Main line",
        endpoint_type=PhoneEndpoint.EndpointType.MAIN_LINE,
    )
    endpoint.normalized_number = ContactMethod.normalize_phone("09 636 5131")
    PhoneEndpoint.objects.bulk_create([endpoint])

    report = DuplicatePhoneReportService().get_report()

    internal = [i for i in report["duplicate_phones"] if i["issue"] == "internal_line"]
    assert len(internal) == 1
    assert internal[0]["endpoint_label"] == "Main line"
    assert len(internal[0]["owners"]) == 1
    assert report["summary"]["internal_line"] == 1


def test_clean_data_returns_empty() -> None:
    company = make_company("Acme Ltd")
    _phone("021 111 111", company=company)

    report = DuplicatePhoneReportService().get_report()

    assert report["duplicate_phones"] == []
    assert report["summary"] == {"cross_company": 0, "internal_line": 0}
    assert "checked_at" in report


def test_one_person_linked_to_two_companies_is_one_phone_owner() -> None:
    """A Person may span companies; unioning their company ids caused a false alert."""
    acme = make_company("Acme Ltd")
    beta = make_company("Beta Ltd")
    person = Person.objects.create(name="Jane Smith")
    first_link = CompanyPersonLink.objects.create(company=acme, person=person)
    CompanyPersonLink.objects.create(company=beta, person=person)
    _phone("021 111 111", contact=first_link)

    report = DuplicatePhoneReportService().get_report()

    assert report["duplicate_phones"] == []


@pytest.mark.urls("apps.company.tests.urls")
class TestEndpoint:
    def test_endpoint_returns_report(self, client: Client) -> None:
        acme = make_company("Acme Ltd")
        beta = make_company("Beta Ltd")
        _phone("021 111 111", company=acme)
        _phone("021 111 111", company=beta)

        response = client.get("/api/job/data-quality/duplicate-phones/")

        assert response.status_code == 200
        body = response.json()
        assert body["summary"] == {"cross_company": 1, "internal_line": 0}
        assert body["duplicate_phones"][0]["issue"] == "cross_company"

    def test_endpoint_requires_office_staff(self, workshop_staff: Staff) -> None:
        client = Client()
        authenticate(client, workshop_staff)
        response = client.get("/api/job/data-quality/duplicate-phones/")
        assert response.status_code == 403
