"""Picking an address candidate on the settings screen fills the geocode columns.

The derived columns are re-read from Google by ``google_place_id``, never taken
from the request body. The id is the only part of a chosen candidate a client
cannot quietly swap for somewhere else, and the re-read is also what puts the
whole reply in our hands to store.

Mocks at the HTTP boundary — Google is never hit here.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from apps.core.models import CompanyDefaults, IntegrationSettings
from apps.core.tests.test_place_lookup import PLACES_RESPONSE

pytestmark = pytest.mark.django_db

URL = "/api/company-defaults/"
GET_TARGET = "apps.core.geocoding.requests.get"
PLACE = PLACES_RESPONSE["places"][0]
PLACE_ID = "ChIJCTlhFsxIDW0RYNfpF_7ReVA"


@pytest.fixture(autouse=True)
def api_key() -> None:
    IntegrationSettings.objects.filter(pk=1).update(google_maps_api_key="test-key")


def _google_ok(payload: object) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def test_picking_a_place_fills_the_geocode_columns(superuser_api: Client) -> None:
    with patch(GET_TARGET, return_value=_google_ok(PLACE)):
        response = superuser_api.patch(
            URL,
            {"google_place_id": PLACE_ID, "city": "Auckland"},
            content_type="application/json",
        )

    assert response.status_code == 200
    defaults = CompanyDefaults.get_solo()
    assert defaults.google_place_id == PLACE_ID
    assert defaults.formatted_address == "151 Captain Springs Road, Onehunga, Auckland 1061"
    assert defaults.region == "Auckland"
    assert defaults.latitude == Decimal("-36.9220862")
    assert defaults.longitude == Decimal("174.8005851")
    # The whole reply, not only the columns above.
    assert defaults.address_raw_json is not None
    assert defaults.address_raw_json["viewport"]


def test_coordinates_posted_by_a_client_are_overwritten_by_the_lookup(
    superuser_api: Client,
) -> None:
    """The id is the only part of the pick that is trusted."""
    with patch(GET_TARGET, return_value=_google_ok(PLACE)):
        superuser_api.patch(
            URL,
            {"google_place_id": PLACE_ID, "latitude": "-41.0", "longitude": "174.0"},
            content_type="application/json",
        )

    defaults = CompanyDefaults.get_solo()
    assert defaults.latitude == Decimal("-36.9220862")
    assert defaults.longitude == Decimal("174.8005851")


def test_clearing_the_place_clears_what_was_derived_from_it(superuser_api: Client) -> None:
    """Otherwise the coordinates outlive the address they described."""
    with patch(GET_TARGET, return_value=_google_ok(PLACE)):
        superuser_api.patch(URL, {"google_place_id": PLACE_ID}, content_type="application/json")

    with patch(GET_TARGET) as google:
        response = superuser_api.patch(
            URL, {"google_place_id": None}, content_type="application/json"
        )

    assert response.status_code == 200
    google.assert_not_called()
    defaults = CompanyDefaults.get_solo()
    assert defaults.google_place_id is None
    assert defaults.formatted_address is None
    assert defaults.region is None
    assert defaults.latitude is None
    assert defaults.address_raw_json is None


def test_a_place_google_no_longer_knows_is_a_400(superuser_api: Client) -> None:
    """Refused rather than stored: an address and its geocode are one fact."""
    with patch(GET_TARGET, return_value=_google_ok({})):
        response = superuser_api.patch(
            URL, {"google_place_id": "gone-123"}, content_type="application/json"
        )

    assert response.status_code == 400
    assert CompanyDefaults.get_solo().google_place_id is None


def test_a_google_outage_is_a_503(superuser_api: Client) -> None:
    refused = MagicMock()
    refused.status_code = 503
    refused.text = "backend error"
    with patch(GET_TARGET, return_value=refused):
        response = superuser_api.patch(
            URL, {"google_place_id": PLACE_ID}, content_type="application/json"
        )

    assert response.status_code == 503


def test_a_patch_that_touches_no_address_never_calls_google(superuser_api: Client) -> None:
    """A settings edit must not depend on a vendor it has nothing to do with."""
    with patch(GET_TARGET) as google:
        response = superuser_api.patch(
            URL, {"company_acronym": "MSM"}, content_type="application/json"
        )

    assert response.status_code == 200
    google.assert_not_called()
