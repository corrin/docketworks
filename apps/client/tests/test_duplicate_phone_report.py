from django.test import TestCase
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.client.services.duplicate_phone_report import DuplicatePhoneReportService
from apps.crm.models import PhoneEndpoint


class DuplicatePhoneReportTests(TestCase):
    def _client(self, name: str) -> Client:
        return Client.objects.create(name=name, xero_last_modified=timezone.now())

    def _phone(
        self,
        value: str,
        client: Client | None = None,
        contact: ClientContact | None = None,
    ) -> ClientContactMethod:
        """Insert a phone method bypassing the save() guard (legacy-style data)."""
        method = ClientContactMethod(
            client=client,
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            value=value,
        )
        method.normalized_value = ClientContactMethod.normalize_phone(value)
        ClientContactMethod.objects.bulk_create([method])
        return method

    def test_detects_cross_client_number(self) -> None:
        acme = self._client("Acme Ltd")
        beta = self._client("Beta Ltd")
        self._phone("021 111 111", client=acme)
        self._phone("021 111 111", client=beta)

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
        client = self._client("Acme Ltd")
        contact = ClientContact.objects.create(client=client, name="Paul Jones")
        self._phone("09 636 5131", contact=contact)
        PhoneEndpoint.objects.create(
            number="09 636 5131",
            label="Main line",
            endpoint_type=PhoneEndpoint.EndpointType.MAIN_LINE,
        )

        report = DuplicatePhoneReportService().get_report()

        internal = [
            i for i in report["duplicate_phones"] if i["issue"] == "internal_line"
        ]
        self.assertEqual(len(internal), 1)
        self.assertEqual(internal[0]["endpoint_label"], "Main line")
        self.assertEqual(len(internal[0]["owners"]), 1)
        self.assertEqual(report["summary"]["internal_line"], 1)

    def test_clean_data_returns_empty(self) -> None:
        client = self._client("Acme Ltd")
        self._phone("021 111 111", client=client)

        report = DuplicatePhoneReportService().get_report()

        self.assertEqual(report["duplicate_phones"], [])
        self.assertEqual(report["summary"], {"cross_client": 0, "internal_line": 0})
        self.assertIn("checked_at", report)
