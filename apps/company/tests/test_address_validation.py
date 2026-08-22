"""Tests for companies_addresses_validate_create + geocoding_service.

Mocks at the HTTP boundary (``requests.post``) — the Google Address
Validation API is never hit.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from apps.company.services.geocoding_service import geocode_address
from apps.core.models import IntegrationSettings

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.company.tests.urls"),
]

PATH = "/api/companies/addresses/validate/"
POST_TARGET = "apps.company.services.geocoding_service.requests.post"

GOOGLE_RESPONSE: dict[str, Any] = {
    "result": {
        "address": {
            "formattedAddress": "12 Depot Road, Penrose, Auckland 1061, New Zealand",
            "addressComponents": [
                {"componentType": "street_number", "componentName": {"text": "12"}},
                {"componentType": "route", "componentName": {"text": "Depot Road"}},
                {"componentType": "sublocality_level_1", "componentName": {"text": "Penrose"}},
                {"componentType": "locality", "componentName": {"text": "Auckland"}},
                {"componentType": "postal_code", "componentName": {"text": "1061"}},
                {"componentType": "country", "componentName": {"text": "New Zealand"}},
            ],
        },
        "geocode": {
            "placeId": "place-123",
            "location": {"latitude": -36.9128, "longitude": 174.8148},
        },
    }
}


def _google_ok(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


@pytest.fixture
def api_key() -> None:
    IntegrationSettings.objects.filter(pk=1).update(google_maps_api_key="test-key")


@pytest.fixture
def no_api_key() -> None:
    IntegrationSettings.objects.filter(pk=1).update(google_maps_api_key=None)


@pytest.mark.usefixtures("api_key")
class TestEndpoint:
    def test_valid_address_returns_structured_candidate(self, client: Client) -> None:
        with patch(POST_TARGET, return_value=_google_ok(GOOGLE_RESPONSE)) as post:
            response = client.post(
                PATH, {"address": "12 depot rd penrose"}, content_type="application/json"
            )

        assert response.status_code == 200
        candidates = response.json()["candidates"]
        assert candidates == [
            {
                "formatted_address": "12 Depot Road, Penrose, Auckland 1061, New Zealand",
                "street": "12 Depot Road",
                "suburb": "Penrose",
                "city": "Auckland",
                "state": "",
                "postal_code": "1061",
                "country": "New Zealand",
                "google_place_id": "place-123",
                "latitude": -36.9128,
                "longitude": 174.8148,
            }
        ]
        # The freetext address reaches Google verbatim (NZ region default).
        sent = post.call_args.kwargs["json"]
        assert sent["address"]["addressLines"] == ["12 depot rd penrose"]
        assert sent["address"]["regionCode"] == "NZ"

    def test_no_match_returns_empty_candidates(self, client: Client) -> None:
        with patch(POST_TARGET, return_value=_google_ok({"result": {}})):
            response = client.post(
                PATH, {"address": "nowhere at all"}, content_type="application/json"
            )

        assert response.status_code == 200
        assert response.json() == {"candidates": []}

    def test_blank_address_is_400(self, client: Client) -> None:
        response = client.post(PATH, {"address": "   "}, content_type="application/json")
        assert response.status_code == 400
        assert response.json()["detail"] == "Address is required"

    def test_google_error_is_503(self, client: Client) -> None:
        error_response = MagicMock()
        error_response.status_code = 403
        error_response.text = "quota exceeded"
        with patch(POST_TARGET, return_value=error_response):
            response = client.post(
                PATH, {"address": "12 Depot Road"}, content_type="application/json"
            )

        assert response.status_code == 503
        assert "403" in response.json()["detail"]


@pytest.mark.usefixtures("no_api_key")
def test_missing_api_key_is_503(client: Client) -> None:
    response = client.post(PATH, {"address": "12 Depot Road"}, content_type="application/json")

    assert response.status_code == 503
    assert response.json()["detail"] == "Address validation service not configured"


@pytest.mark.usefixtures("api_key")
def test_geocode_address_builds_street_from_number_and_route() -> None:
    with patch(POST_TARGET, return_value=_google_ok(GOOGLE_RESPONSE)):
        result = geocode_address("12 depot rd")

    assert result is not None
    assert result.street == "12 Depot Road"
    assert result.country == "New Zealand"
