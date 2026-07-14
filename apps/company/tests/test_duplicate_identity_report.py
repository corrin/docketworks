from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.duplicate_identity_report import (
    DuplicateIdentityReportService,
)
from apps.testing import BaseTestCase


class DuplicateIdentityReportTests(BaseTestCase):
    def _company(self, name: str) -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def _method(self, owner: Company | Person, method_type: str, value: str) -> None:
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

    def test_exact_company_names_are_one_automatic_group(self) -> None:
        self._company("Acme Limited")
        self._company("CASH SALE - Acme Ltd")

        report = DuplicateIdentityReportService().get_report()

        self.assertEqual(report["summary"]["company_merge_groups"], 1)
        group = report["company_groups"][0]
        self.assertEqual(group["recommendation"], "merge")
        self.assertEqual(len(group["members"]), 2)

    def test_unrelated_company_names_with_shared_email_and_phone_need_review(
        self,
    ) -> None:
        first = self._company("Acme Engineering")
        second = self._company("Jane Smith")
        for company in (first, second):
            self._method(company, ContactMethod.MethodType.EMAIL, "jane@acme.test")
            self._method(company, ContactMethod.MethodType.PHONE, "021 555 0101")

        report = DuplicateIdentityReportService().get_report()

        self.assertEqual(report["summary"]["company_merge_groups"], 0)
        self.assertEqual(report["summary"]["company_review_groups"], 1)

    def test_compatible_people_with_a_rare_phone_are_merged(self) -> None:
        company = self._company("Acme")
        first = Person.objects.create(name="Robert Jones")
        second = Person.objects.create(name="Bob Jones")
        CompanyPersonLink.objects.create(company=company, person=first)
        CompanyPersonLink.objects.create(company=company, person=second)
        self._method(first, ContactMethod.MethodType.PHONE, "021 555 0102")
        self._method(second, ContactMethod.MethodType.PHONE, "021 555 0102")

        report = DuplicateIdentityReportService().get_report()

        self.assertEqual(report["summary"]["person_merge_groups"], 1)

    def test_conflicting_person_names_with_shared_contacts_need_review(self) -> None:
        first = Person.objects.create(name="Alice Smith")
        second = Person.objects.create(name="Bob Jones")
        for person in (first, second):
            self._method(person, ContactMethod.MethodType.EMAIL, "office@acme.test")
            self._method(person, ContactMethod.MethodType.PHONE, "021 555 0103")

        report = DuplicateIdentityReportService().get_report()

        self.assertEqual(report["summary"]["person_merge_groups"], 0)
        self.assertEqual(report["summary"]["person_review_groups"], 1)

    def test_cross_company_name_only_people_are_not_reported(self) -> None:
        first_company = self._company("Acme")
        second_company = self._company("Beta")
        first = Person.objects.create(name="Chris Smith")
        second = Person.objects.create(name="Chris Smith")
        CompanyPersonLink.objects.create(company=first_company, person=first)
        CompanyPersonLink.objects.create(company=second_company, person=second)

        report = DuplicateIdentityReportService().get_report()

        self.assertEqual(report["person_groups"], [])
