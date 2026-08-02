"""One-number-one-owner symmetry: PhoneEndpoint side of the guard.

Ported from v1 apps/crm/tests/test_phone_endpoint_guard.py.
ContactMethod.save() refuses numbers held by an active PhoneEndpoint;
these tests cover the mirror — an active endpoint cannot claim a number a
company already owns, or that company's calls silently become INTERNAL.
"""

from collections.abc import Iterator
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.company.models import Company, ContactMethod
from apps.crm.models import PhoneEndpoint
from apps.crm.tests.helpers import cookie_client, link_person, make_company, make_superuser

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.crm.tests.urls"),
]

ENDPOINTS_PATH = "/api/crm/phone-endpoints/"


def _client_phone(company: Company, value: str = "021 555 123") -> ContactMethod:
    return ContactMethod.objects.create(
        company=company,
        method_type=ContactMethod.MethodType.PHONE,
        value=value,
    )


def _endpoint(number: str, **overrides: object) -> PhoneEndpoint:
    fields: dict[str, object] = {
        "number": number,
        "label": "Test line",
        "endpoint_type": PhoneEndpoint.EndpointType.MAIN_LINE,
    }
    fields.update(overrides)
    return PhoneEndpoint.objects.create(**fields)


class TestPhoneEndpointGuardModel:
    def test_create_active_endpoint_over_client_number_raises(self) -> None:
        _client_phone(make_company("Acme Ltd"))

        with pytest.raises(ValidationError, match=r"already belongs to.*company Acme Ltd"):
            _endpoint("021 555 123")

    def test_error_names_owning_contact(self) -> None:
        contact = link_person(make_company("Acme Ltd"), "Jane Smith")
        ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )

        with pytest.raises(ValidationError, match="person Jane Smith"):
            _endpoint("021 555 123")

    def test_inactive_endpoint_over_client_number_is_allowed(self) -> None:
        _client_phone(make_company())

        endpoint = _endpoint("021 555 123", is_active=False)

        assert endpoint.pk is not None

    def test_reactivating_endpoint_over_client_number_raises(self) -> None:
        _client_phone(make_company())
        endpoint = _endpoint("021 555 123", is_active=False)

        endpoint.is_active = True
        with pytest.raises(ValidationError, match="already belongs to"):
            endpoint.save()

    def test_changing_number_onto_client_number_raises(self) -> None:
        _client_phone(make_company())
        endpoint = _endpoint("09 555 000")

        endpoint.number = "021 555 123"
        with pytest.raises(ValidationError, match="already belongs to"):
            endpoint.save()

    def test_existing_endpoint_resave_is_grandfathered(self) -> None:
        """Legacy overlap: re-saving an unchanged endpoint must not start failing."""
        endpoint = _endpoint("021 555 123")
        # Legacy cross-owned row inserted bypassing the method-side guard,
        # as pre-guard data was.
        legacy = ContactMethod(
            company=make_company(),
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        legacy.normalized_value = ContactMethod.normalize_phone("021 555 123")
        ContactMethod.objects.bulk_create([legacy])

        endpoint.label = "Renamed line"
        endpoint.save()  # number/is_active unchanged -> grandfathered

        endpoint.refresh_from_db()
        assert endpoint.label == "Renamed line"


@pytest.fixture
def api() -> Client:
    return cookie_client(make_superuser("crm-endpoint-admin@example.com"))


@pytest.fixture(autouse=True)
def rematch_delay() -> Iterator[mock.MagicMock]:
    """Endpoint CRUD queues a rematch task; keep the broker out of API tests."""
    with mock.patch("apps.crm.api.rematch_phone_calls_task") as task:
        yield task


class TestPhoneEndpointGuardApi:
    def test_create_endpoint_over_client_number_returns_400(self, api: Client) -> None:
        _client_phone(make_company("Acme Ltd"))

        response = api.post(
            ENDPOINTS_PATH,
            data={
                "number": "021 555 123",
                "label": "Main line",
                "endpoint_type": "main_line",
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "already belongs to" in response.json()["number"][0]
        assert not PhoneEndpoint.objects.filter(normalized_number="+6421555123").exists()

    def test_update_unrelated_field_on_grandfathered_endpoint_succeeds(self, api: Client) -> None:
        endpoint = _endpoint("021 555 123")
        legacy = ContactMethod(
            company=make_company(),
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        legacy.normalized_value = ContactMethod.normalize_phone("021 555 123")
        ContactMethod.objects.bulk_create([legacy])

        response = api.patch(
            f"{ENDPOINTS_PATH}{endpoint.id}/",
            data={"label": "Renamed line"},
            content_type="application/json",
        )

        assert response.status_code == 200
        endpoint.refresh_from_db()
        assert endpoint.label == "Renamed line"

    def test_changing_number_onto_client_number_returns_400(self, api: Client) -> None:
        _client_phone(make_company("Acme Ltd"))
        endpoint = _endpoint("09 555 000")

        response = api.patch(
            f"{ENDPOINTS_PATH}{endpoint.id}/",
            data={"number": "021 555 123"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "already belongs to" in response.json()["number"][0]

    def test_create_endpoint_queues_rematch_for_its_number(
        self, api: Client, rematch_delay: mock.MagicMock
    ) -> None:
        """Historical calls to a newly declared internal number must reclassify."""
        response = api.post(
            ENDPOINTS_PATH,
            data={
                "number": "09 555 111",
                "label": "New line",
                "endpoint_type": "main_line",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        assert response.json()["normalized_number"] == "+649555111"
        rematch_delay.delay.assert_called_once_with(["+649555111"])
