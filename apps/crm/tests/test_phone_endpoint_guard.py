"""One-number-one-owner symmetry: PhoneEndpoint side of the guard.

ContactMethod.save() refuses numbers held by an active PhoneEndpoint;
these tests cover the mirror — an active endpoint cannot claim a number a
company already owns, or that company's calls silently become INTERNAL.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.crm.models import PhoneEndpoint
from apps.testing import BaseAPITestCase


def _client(name: str = "Acme Ltd") -> Company:
    return Company.objects.create(name=name, xero_last_modified=timezone.now())


def _client_phone(company: Company, value: str = "021 555 123") -> ContactMethod:
    return ContactMethod.objects.create(
        company=company,
        method_type=ContactMethod.MethodType.PHONE,
        value=value,
    )


def _link(company: Company, name: str) -> CompanyPersonLink:
    person = Person.objects.create(name=name)
    return CompanyPersonLink.objects.create(
        company=company,
        person=person,
    )


def _endpoint(number: str, **overrides: object) -> PhoneEndpoint:
    fields: dict[str, object] = {
        "number": number,
        "label": "Test line",
        "endpoint_type": PhoneEndpoint.EndpointType.MAIN_LINE,
    }
    fields.update(overrides)
    return PhoneEndpoint.objects.create(**fields)


class PhoneEndpointGuardModelTests(TestCase):
    def test_create_active_endpoint_over_client_number_raises(self) -> None:
        _client_phone(_client("Acme Ltd"))

        with self.assertRaisesRegex(
            ValidationError, "already belongs to.*company Acme Ltd"
        ):
            _endpoint("021 555 123")

    def test_error_names_owning_contact(self) -> None:
        contact = _link(_client("Acme Ltd"), "Jane Smith")
        ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )

        with self.assertRaisesRegex(ValidationError, "person Jane Smith"):
            _endpoint("021 555 123")

    def test_inactive_endpoint_over_client_number_is_allowed(self) -> None:
        _client_phone(_client())

        endpoint = _endpoint("021 555 123", is_active=False)

        self.assertIsNotNone(endpoint.pk)

    def test_reactivating_endpoint_over_client_number_raises(self) -> None:
        _client_phone(_client())
        endpoint = _endpoint("021 555 123", is_active=False)

        endpoint.is_active = True
        with self.assertRaisesRegex(ValidationError, "already belongs to"):
            endpoint.save()

    def test_changing_number_onto_client_number_raises(self) -> None:
        _client_phone(_client())
        endpoint = _endpoint("09 555 000")

        endpoint.number = "021 555 123"
        with self.assertRaisesRegex(ValidationError, "already belongs to"):
            endpoint.save()

    def test_existing_endpoint_resave_is_grandfathered(self) -> None:
        """Legacy overlap: re-saving an unchanged endpoint must not start failing."""
        endpoint = _endpoint("021 555 123")
        # Legacy cross-owned row inserted bypassing the method-side guard,
        # as pre-guard data was.
        legacy = ContactMethod(
            company=_client(),
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        legacy.normalized_value = ContactMethod.normalize_phone("021 555 123")
        ContactMethod.objects.bulk_create([legacy])

        endpoint.label = "Renamed line"
        endpoint.save()  # number/is_active unchanged -> grandfathered

        endpoint.refresh_from_db()
        self.assertEqual(endpoint.label, "Renamed line")


class PhoneEndpointGuardApiTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.superuser = Staff.objects.create_user(
            email="crm-endpoint-admin@example.com",
            password="testpass",
            is_superuser=True,
            is_office_staff=True,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.superuser)

    def test_create_endpoint_over_client_number_returns_400(self) -> None:
        _client_phone(_client("Acme Ltd"))

        response = self.api.post(
            "/api/crm/phone-endpoints/",
            {
                "number": "021 555 123",
                "label": "Main line",
                "endpoint_type": "main_line",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already belongs to", response.data["number"][0])
        self.assertFalse(
            PhoneEndpoint.objects.filter(normalized_number="+6421555123").exists()
        )

    def test_update_unrelated_field_on_grandfathered_endpoint_succeeds(self) -> None:
        endpoint = _endpoint("021 555 123")
        legacy = ContactMethod(
            company=_client(),
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        legacy.normalized_value = ContactMethod.normalize_phone("021 555 123")
        ContactMethod.objects.bulk_create([legacy])

        response = self.api.patch(
            f"/api/crm/phone-endpoints/{endpoint.id}/",
            {"label": "Renamed line"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        endpoint.refresh_from_db()
        self.assertEqual(endpoint.label, "Renamed line")

    def test_changing_number_onto_client_number_returns_400(self) -> None:
        _client_phone(_client("Acme Ltd"))
        endpoint = _endpoint("09 555 000")

        response = self.api.patch(
            f"/api/crm/phone-endpoints/{endpoint.id}/",
            {"number": "021 555 123"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already belongs to", response.data["number"][0])
