from django.test import TestCase
from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.duplicate_phone_report import DuplicatePhoneReportService
from apps.crm.models import PhoneEndpoint


class DuplicatePhoneReportTests(TestCase):
    def _company(self, name: str) -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def _phone(
        self,
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

    def _link(self, company: Company, name: str) -> CompanyPersonLink:
        person = Person.objects.create(name=name)
        return CompanyPersonLink.objects.create(
            company=company,
            person=person,
            xero_name=name,
        )

    def test_detects_cross_company_number(self) -> None:
        acme = self._company("Acme Ltd")
        beta = self._company("Beta Ltd")
        self._phone("021 111 111", company=acme)
        self._phone("021 111 111", company=beta)

        report = DuplicatePhoneReportService().get_report()

        cross = [i for i in report["duplicate_phones"] if i["issue"] == "cross_client"]
        self.assertEqual(len(cross), 1)
        self.assertEqual(
            cross[0]["normalized_value"],
            ContactMethod.normalize_phone("021 111 111"),
        )
        self.assertEqual(len(cross[0]["owners"]), 2)
        self.assertEqual(report["summary"]["cross_client"], 1)

    def test_detects_internal_line_collision(self) -> None:
        company = self._company("Acme Ltd")
        contact = self._link(company, "Paul Jones")
        self._phone("09 636 5131", contact=contact)
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

        internal = [
            i for i in report["duplicate_phones"] if i["issue"] == "internal_line"
        ]
        self.assertEqual(len(internal), 1)
        self.assertEqual(internal[0]["endpoint_label"], "Main line")
        self.assertEqual(len(internal[0]["owners"]), 1)
        self.assertEqual(report["summary"]["internal_line"], 1)

    def test_clean_data_returns_empty(self) -> None:
        company = self._company("Acme Ltd")
        self._phone("021 111 111", company=company)

        report = DuplicatePhoneReportService().get_report()

        self.assertEqual(report["duplicate_phones"], [])
        self.assertEqual(report["summary"], {"cross_client": 0, "internal_line": 0})
        self.assertIn("checked_at", report)
