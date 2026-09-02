"""The address-candidate endpoint: ``companies_addresses_validate_create``.

Mocks at the HTTP boundary (``requests.post``) — Google is never hit here. The
captured reply lives in ``test_place_lookup``; it is real, and reusing it keeps
one recorded example of what this API actually returns rather than two hopeful
ones.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from apps.core.models import IntegrationSettings
from apps.core.tests.test_place_lookup import PLACES_RESPONSE

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.company.tests.urls"),
]

PATH = "/api/companies/addresses/validate/"
POST_TARGET = "apps.core.geocoding.requests.post"


def _google_ok(payload: object) -> MagicMock:
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
    def test_a_match_returns_a_candidate_carrying_its_region(self, client: Client) -> None:
        with patch(POST_TARGET, return_value=_google_ok(PLACES_RESPONSE)) as post:
            response = client.post(
                PATH, {"address": "151 captain springs rd"}, content_type="application/json"
            )

        assert response.status_code == 200
        assert response.json()["candidates"] == [
            {
                "formatted_address": "151 Captain Springs Road, Onehunga, Auckland 1061",
                "street": "151 Captain Springs Road",
                "suburb": "Onehunga",
                "city": "Auckland",
                "region": "Auckland",
                "nz_subdivision": "AUK",
                "postal_code": "1061",
                "country": "New Zealand",
                "google_place_id": "ChIJCTlhFsxIDW0RYNfpF_7ReVA",
                "latitude": -36.922086199999995,
                "longitude": 174.80058509999998,
            }
        ]
        # The freetext reaches Google verbatim, scoped to NZ.
        sent = post.call_args.kwargs["json"]
        assert sent["textQuery"] == "151 captain springs rd"
        assert sent["regionCode"] == "NZ"

    def test_the_key_is_a_header_and_never_the_url(self, client: Client) -> None:
        """A URL carrying the key is copied into every RequestException, and so into AppError."""
        with patch(POST_TARGET, return_value=_google_ok(PLACES_RESPONSE)) as post:
            client.post(
                PATH, {"address": "151 captain springs rd"}, content_type="application/json"
            )

        assert post.call_args.kwargs["headers"]["X-Goog-Api-Key"] == "test-key"
        assert "params" not in post.call_args.kwargs
        assert "test-key" not in post.call_args.args[0]

    def test_the_whole_google_reply_does_not_reach_the_browser(self, client: Client) -> None:
        """It belongs in the database, not on a keystroke-rate response."""
        with patch(POST_TARGET, return_value=_google_ok(PLACES_RESPONSE)):
            response = client.post(
                PATH, {"address": "151 captain springs rd"}, content_type="application/json"
            )

        candidate = response.json()["candidates"][0]
        assert "raw" not in candidate
        assert "viewport" not in candidate
        assert "postalAddress" not in candidate

    def test_no_match_returns_empty_candidates(self, client: Client) -> None:
        with patch(POST_TARGET, return_value=_google_ok({"places": []})):
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
                PATH, {"address": "151 Captain Springs Road"}, content_type="application/json"
            )

        assert response.status_code == 503
        assert "403" in response.json()["detail"]


@pytest.mark.usefixtures("no_api_key")
def test_missing_api_key_is_503(client: Client) -> None:
    response = client.post(
        PATH, {"address": "151 Captain Springs Road"}, content_type="application/json"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Address validation service not configured"
