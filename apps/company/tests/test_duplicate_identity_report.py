"""Tests for the duplicate-identities report and its endpoint (ported from v1).

Includes the name-compatibility behaviours v1 asserted in
test_duplicate_person_report.py — the helpers now live in
``duplicate_identity_report`` (the person report was the superseded sibling,
ADR 0039).
"""

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.duplicate_identity_report import (
    DuplicateIdentityReportService,
    person_names_compatible,
)
from apps.company.tests.conftest import authenticate, make_company

pytestmark = pytest.mark.django_db


def _method(owner: Company | Person, method_type: str, value: str) -> None:
    normalized = (
        value.strip().casefold()
        if method_type == ContactMethod.MethodType.EMAIL
        else ContactMethod.normalize_phone(value)
    )
    method = ContactMethod(
        method_type=method_type,
        value=value,
        normalized_value=normalized,
        company=owner if isinstance(owner, Company) else None,
        person=owner if isinstance(owner, Person) else None,
    )
    ContactMethod.objects.bulk_create([method])


class TestReport:
    def test_exact_company_names_are_one_automatic_group(self) -> None:
        make_company("Acme Limited")
        make_company("CASH SALE - Acme Ltd")

        report = DuplicateIdentityReportService().get_report()

        assert report["summary"]["company_merge_groups"] == 1
        group = report["company_groups"][0]
        assert group["recommendation"] == "merge"
        assert len(group["members"]) == 2

    def test_unrelated_company_names_with_shared_email_and_phone_need_review(
        self,
    ) -> None:
        first = make_company("Acme Engineering")
        second = make_company("Jane Smith")
        for company in (first, second):
            _method(company, ContactMethod.MethodType.EMAIL, "jane@acme.test")
            _method(company, ContactMethod.MethodType.PHONE, "021 555 0101")

        report = DuplicateIdentityReportService().get_report()

        assert report["summary"]["company_merge_groups"] == 0
        assert report["summary"]["company_review_groups"] == 1

    def test_compatible_people_with_a_rare_phone_are_merged(self) -> None:
        company = make_company("Acme")
        first = Person.objects.create(name="Robert Jones")
        second = Person.objects.create(name="Bob Jones")
        CompanyPersonLink.objects.create(company=company, person=first)
        CompanyPersonLink.objects.create(company=company, person=second)
        _method(first, ContactMethod.MethodType.PHONE, "021 555 0102")
        _method(second, ContactMethod.MethodType.PHONE, "021 555 0102")

        report = DuplicateIdentityReportService().get_report()

        assert report["summary"]["person_merge_groups"] == 1

    def test_conflicting_person_names_with_shared_contacts_need_review(self) -> None:
        first = Person.objects.create(name="Alice Smith")
        second = Person.objects.create(name="Bob Jones")
        for person in (first, second):
            _method(person, ContactMethod.MethodType.EMAIL, "office@acme.test")
            _method(person, ContactMethod.MethodType.PHONE, "021 555 0103")

        report = DuplicateIdentityReportService().get_report()

        assert report["summary"]["person_merge_groups"] == 0
        assert report["summary"]["person_review_groups"] == 1

    def test_cross_company_name_only_people_are_not_reported(self) -> None:
        first_company = make_company("Acme")
        second_company = make_company("Beta")
        first = Person.objects.create(name="Chris Smith")
        second = Person.objects.create(name="Chris Smith")
        CompanyPersonLink.objects.create(company=first_company, person=first)
        CompanyPersonLink.objects.create(company=second_company, person=second)

        report = DuplicateIdentityReportService().get_report()

        assert report["person_groups"] == []


class TestPersonNamesCompatible:
    """Name-compatibility behaviours from v1 test_duplicate_person_report.py."""

    def test_nickname_does_not_override_conflicting_surnames(self) -> None:
        assert person_names_compatible("Robert Grant", "Rob Smith") is False

    def test_nickname_with_matching_surname_is_compatible(self) -> None:
        assert person_names_compatible("Robert Jones", "Bob Jones") is True

    def test_custom_overlapping_alias_groups_preserve_any_canonical_match(self) -> None:
        alias_groups = {
            "robert": {"rob"},
            "robin": {"rob", "bob"},
        }

        assert person_names_compatible("Rob Grant", "Bob Grant", alias_groups=alias_groups)
        assert not person_names_compatible("Rob Grant", "Bob Smith", alias_groups=alias_groups)


@pytest.mark.urls("apps.company.tests.urls")
class TestEndpoint:
    def test_endpoint_returns_report(self, client: Client) -> None:
        make_company("Acme Limited")
        make_company("CASH SALE - Acme Ltd")

        response = client.get("/api/job/data-quality/duplicate-identities/")

        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["company_merge_groups"] == 1
        group = body["company_groups"][0]
        assert group["recommendation"] == "merge"
        assert group["canonical_id"] is not None
        assert len(group["members"]) == 2
        assert body["person_groups"] == []

    def test_endpoint_requires_office_staff(self, workshop_staff: Staff) -> None:
        client = Client()
        authenticate(client, workshop_staff)
        response = client.get("/api/job/data-quality/duplicate-identities/")
        assert response.status_code == 403
