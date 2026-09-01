"""Places (New) lookups for the shop's own address.

``PLACES_RESPONSE`` is a real reply, captured 2026-09-02 for 151 Captain
Springs Road and pasted verbatim. That matters: the hand-written Address
Validation mock this file replaced carried no ``administrative_area_level_1``,
and because of it nobody noticed for a year that the product never returns a
region for NZ at all. A mock authored from documentation asserts what we hoped
an API does; this one asserts what it did.

Mocks at the HTTP boundary (``requests.post``) — Google is never hit here. The
live call has its own test, marked ``integration`` (ADR 0050).
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from apps.core.geocoding import (
    GeocodingError,
    nz_subdivision_for_region,
    search_places,
)

POST_TARGET = "apps.core.geocoding.requests.post"

PLACES_RESPONSE: dict[str, Any] = {
    "places": [
        {
            "addressComponents": [
                {
                    "languageCode": "en-US",
                    "longText": "151",
                    "shortText": "151",
                    "types": ["street_number"],
                },
                {
                    "languageCode": "en",
                    "longText": "Captain Springs Road",
                    "shortText": "Captain Springs Rd",
                    "types": ["route"],
                },
                {
                    "languageCode": "en",
                    "longText": "Onehunga",
                    "shortText": "Onehunga",
                    "types": ["sublocality_level_1", "sublocality", "political"],
                },
                {
                    "languageCode": "en",
                    "longText": "Auckland",
                    "shortText": "Auckland",
                    "types": ["locality", "political"],
                },
                {
                    "languageCode": "en",
                    "longText": "Auckland",
                    "shortText": "Auckland",
                    "types": ["administrative_area_level_1", "political"],
                },
                {
                    "languageCode": "en",
                    "longText": "New Zealand",
                    "shortText": "NZ",
                    "types": ["country", "political"],
                },
                {
                    "languageCode": "en-US",
                    "longText": "1061",
                    "shortText": "1061",
                    "types": ["postal_code"],
                },
            ],
            "formattedAddress": "151 Captain Springs Road, Onehunga, Auckland 1061",
            "id": "ChIJCTlhFsxIDW0RYNfpF_7ReVA",
            "location": {"latitude": -36.922086199999995, "longitude": 174.80058509999998},
            "postalAddress": {
                "addressLines": ["151 Captain Springs Road"],
                "languageCode": "en-US",
                "locality": "Auckland",
                "postalCode": "1061",
                "regionCode": "NZ",
                "sublocality": "Onehunga",
            },
            "shortFormattedAddress": "151 Captain Springs Rd, Onehunga, Auckland",
            "types": ["subpremise", "street_address"],
            "viewport": {
                "high": {"latitude": -36.92074726970849, "longitude": 174.80183338029147},
                "low": {"latitude": -36.92344523029149, "longitude": 174.7991354197085},
            },
        }
    ]
}


def _ok(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def test_a_lookup_reads_the_region_and_maps_it_to_a_holiday_subdivision() -> None:
    """The region is the whole reason this product is called instead of the other one."""
    with patch(POST_TARGET, return_value=_ok(PLACES_RESPONSE)):
        found = search_places("151 Captain Springs Road, Onehunga, Auckland", api_key="k")
        place = found[0] if found else None

    assert place is not None
    assert place.region == "Auckland"
    assert place.nz_subdivision == "AUK"
    assert place.formatted_address == "151 Captain Springs Road, Onehunga, Auckland 1061"
    assert place.place_id == "ChIJCTlhFsxIDW0RYNfpF_7ReVA"
    assert place.latitude == pytest.approx(-36.9220862)
    assert place.longitude == pytest.approx(174.8005851)


def test_the_whole_reply_is_kept_not_only_the_fields_read_today() -> None:
    """Re-fetching a field we already paid for is the failure this guards."""
    with patch(POST_TARGET, return_value=_ok(PLACES_RESPONSE)):
        place = search_places("151 Captain Springs Road", api_key="k")[0]

    assert place is not None
    # None of these are read by PlaceLookup's own fields, which is the point.
    assert place.raw["viewport"]
    assert place.raw["types"] == ["subpremise", "street_address"]
    assert place.raw["shortFormattedAddress"]
    postal_address = place.raw["postalAddress"]
    assert isinstance(postal_address, dict)
    assert postal_address["sublocality"] == "Onehunga"


def test_the_key_travels_in_a_header_never_the_query_string() -> None:
    """A key in a URL reaches the AppError table on the first network blip."""
    with patch(POST_TARGET, return_value=_ok(PLACES_RESPONSE)) as post:
        search_places("151 Captain Springs Road", api_key="secret-key")

    args, kwargs = post.call_args
    url = args[0] if args else kwargs["url"]
    assert kwargs["headers"]["X-Goog-Api-Key"] == "secret-key"
    assert "secret-key" not in url
    assert "params" not in kwargs


def test_no_match_is_an_answer_not_an_error() -> None:
    """A typo returns nothing; that is a real outcome, not a failure."""
    with patch(POST_TARGET, return_value=_ok({"places": []})):
        assert search_places("qqqzzz not an address", api_key="k") == []


def test_a_refused_call_raises_rather_than_reporting_no_match() -> None:
    """A 403 must not look like 'Google knows of no such place'."""
    refused = MagicMock()
    refused.status_code = 403
    refused.text = "IP address restriction"
    with patch(POST_TARGET, return_value=refused), pytest.raises(GeocodingError, match="403"):
        search_places("151 Captain Springs Road", api_key="k")


def test_an_empty_address_never_reaches_google() -> None:
    with patch(POST_TARGET) as post, pytest.raises(ValueError, match="empty address"):
        search_places("", api_key="k")
    post.assert_not_called()


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        # Google suffixes most regions but not Auckland — both must map.
        ("Canterbury Region", "CAN"),
        ("Auckland", "AUK"),
        ("Wellington Region", "WGN"),
        ("Otago Region", "OTA"),
        ("Nelson Region", "NSN"),
        # Māori names come free with the package's own alias table.
        ("Waitaha", "CAN"),
        # A region Google names and the package does not know is a gap, not a crash.
        ("Atlantis Region", None),
        ("", None),
    ],
)
def test_region_wording_maps_to_the_subdivision_code(region: str, expected: str | None) -> None:
    assert nz_subdivision_for_region(region) == expected


def test_south_canterbury_cannot_be_told_from_canterbury() -> None:
    """A recorded limit, not an oversight.

    ``holidays`` carries South Canterbury as its own subdivision with its own
    anniversary day, but Google answers "Canterbury Region" for Timaru exactly
    as it does for Christchurch. A South Canterbury business needs its
    subdivision set by hand, and this test is where that is written down.
    """
    assert nz_subdivision_for_region("Canterbury Region") == "CAN"
    assert nz_subdivision_for_region("South Canterbury") is None
