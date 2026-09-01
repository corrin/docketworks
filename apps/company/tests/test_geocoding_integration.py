"""The Places and Address Validation calls against the real APIs (ADR 0050).

Closes the gap recorded in ``docs/rewrite-status.md``: the outbound-link probe
skips ``v1:validateAddress`` because it is POST-only, so nothing proved either
endpoint existed. A fake provider could only have confirmed what we already
believed — and what we believed was wrong. Address Validation returns no region
for New Zealand, which is why the shop's address goes through Places.

Read-only: both calls look up a public address and write nothing anywhere.

**A 403 naming an IP address is not a code failure.** The key is IP-restricted
and this machine's egress address has been observed to change mid-session; check
the allowlist in the GCP project before reading anything into the error.
"""

import pytest

from apps.company.services.geocoding_service import geocode_address, look_up_place

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _credentials(integration_credentials: None) -> None:
    """Bring the Maps key across from the dev database (ADR 0050)."""


# A public address, chosen because its region and its city differ: Christchurch
# sits in "Canterbury Region", so a lookup that returned the city where the
# region belongs would pass against an Auckland address and fail here.
ADDRESS = "45 Sir William Pickering Drive, Burnside, Christchurch, New Zealand"


class TestPlacesLookup:
    def test_a_real_lookup_returns_a_region_and_its_subdivision(self) -> None:
        place = look_up_place(ADDRESS)

        assert place is not None
        assert place.region == "Canterbury Region"
        assert place.nz_subdivision == "CAN"
        assert place.latitude is not None
        assert place.longitude is not None
        assert place.place_id != ""

    def test_the_whole_reply_is_kept(self) -> None:
        """The stored response must carry more than the fields read today."""
        place = look_up_place(ADDRESS)

        assert place is not None
        assert {"viewport", "types", "postalAddress"} <= set(place.raw)

    def test_an_address_google_cannot_match_returns_nothing(self) -> None:
        assert look_up_place("qqqzzz nowhere at all 99999, New Zealand") is None


class TestAddressValidation:
    def test_the_supplier_path_still_reaches_google(self) -> None:
        """Unchanged by the Places work; this is the PO-entry autocomplete."""
        result = geocode_address(ADDRESS)

        assert result is not None
        assert result.city == "Christchurch"
        assert result.latitude is not None

    def test_address_validation_supplies_no_new_zealand_region(self) -> None:
        """The measurement the whole design rests on, kept as a live check.

        If Google ever starts returning ``administrative_area_level_1`` here,
        this fails — and the second API call for the shop's address stops being
        necessary. That is worth being told about rather than discovering years
        later, which is exactly what happened the first time.
        """
        result = geocode_address(ADDRESS)

        assert result is not None
        assert result.state == ""
