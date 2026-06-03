import importlib

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod

_migration_module = importlib.import_module(
    "apps.client.migrations.0021_clientcontactmethod"
)


class ClientContactMethodMigrationTests(TestCase):
    def test_backfill_creates_canonical_contact_methods(self) -> None:
        client = Client.objects.create(
            name="Acme Ltd",
            email="INFO@ACME.TEST",
            phone="09 111 1111",
            all_phones=[
                {"type": "DEFAULT", "number": "09 111 1111"},
                {"type": "MOBILE", "number": "021 222 333"},
                {"phone_type": "Duplicate Mobile", "phone_number": "+64 21 222 333"},
                {"PhoneType": "Office", "PhoneNumber": "03 444 5555"},
                {"PhoneType": "Fax", "PhoneNumberString": "04 666 7777"},
            ],
            xero_last_modified=timezone.now(),
        )
        contact = ClientContact.objects.create(
            client=client,
            name="Jane Smith",
            email="JANE@ACME.TEST",
            phone="027 888 9999",
        )
        ClientContact.objects.create(
            client=client,
            name="Inactive Person",
            email="inactive@acme.test",
            phone="027 000 0000",
            is_active=False,
        )

        _migration_module.backfill_contact_methods(django_apps, schema_editor=None)

        methods = list(
            ClientContactMethod.objects.order_by(
                "method_type",
                "client_id",
                "contact_id",
                "normalized_value",
            )
        )

        self.assertEqual(len(methods), 7)
        self.assertEqual(
            {
                (
                    method.client_id,
                    method.contact_id,
                    method.method_type,
                    method.value,
                    method.normalized_value,
                    method.label,
                    method.is_primary,
                    method.source,
                )
                for method in methods
            },
            {
                (
                    client.id,
                    None,
                    "email",
                    "INFO@ACME.TEST",
                    "info@acme.test",
                    "Main",
                    True,
                    "imported",
                ),
                (
                    client.id,
                    None,
                    "phone",
                    "09 111 1111",
                    "+6491111111",
                    "Main",
                    True,
                    "imported",
                ),
                (
                    client.id,
                    None,
                    "phone",
                    "021 222 333",
                    "+6421222333",
                    "MOBILE",
                    False,
                    "imported",
                ),
                (
                    client.id,
                    None,
                    "phone",
                    "03 444 5555",
                    "+6434445555",
                    "Office",
                    False,
                    "imported",
                ),
                (
                    client.id,
                    None,
                    "phone",
                    "04 666 7777",
                    "+6446667777",
                    "Fax",
                    False,
                    "imported",
                ),
                (
                    None,
                    contact.id,
                    "email",
                    "JANE@ACME.TEST",
                    "jane@acme.test",
                    "Main",
                    True,
                    "imported",
                ),
                (
                    None,
                    contact.id,
                    "phone",
                    "027 888 9999",
                    "+64278889999",
                    "Main",
                    True,
                    "imported",
                ),
            },
        )
