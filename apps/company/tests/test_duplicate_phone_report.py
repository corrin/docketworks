from django.test import TestCase
from django.utils import timezone

from apps.company.models import ClientContact, ClientContactMethod, Company
from apps.company.services.duplicate_phone_report import DuplicatePhoneReportService
from apps.crm.models import PhoneEndpoint


class DuplicatePhoneReportTests(TestCase):
    def _company(self, name: str) -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def _phone(
        self,
        value: str,
        company: Company | None = None,
        contact: ClientContact | None = None,
    ) -> ClientContactMethod:
        """Insert a phone method bypassing the save() guard (legacy-style data)."""
        method = ClientContactMethod(
            company=company,
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value=value,
        )
        method.normalized_value = ClientContactMethod.normalize_phone(value)
        ClientContactMethod.objects.bulk_create([method])
        return method

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
            ClientContactMethod.normalize_phone("021 111 111"),
        )
        self.assertEqual(len(cross[0]["owners"]), 2)
        self.assertEqual(report["summary"]["cross_client"], 1)

    def test_detects_internal_line_collision(self) -> None:
        company = self._company("Acme Ltd")
        contact = ClientContact.objects.create(company=company, name="Paul Jones")
        self._phone("09 636 5131", contact=contact)
        # Bypass PhoneEndpoint.save()'s collision guard (legacy-style data):
        # the report exists precisely to surface rows that predate the guard.
        endpoint = PhoneEndpoint(
            number="09 636 5131",
            label="Main line",
            endpoint_type=PhoneEndpoint.EndpointType.MAIN_LINE,
        )
        endpoint.normalized_number = ClientContactMethod.normalize_phone("09 636 5131")
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
