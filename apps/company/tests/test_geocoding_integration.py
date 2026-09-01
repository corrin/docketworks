"""Places (New) against the real API (ADR 0050).

Closes the gap recorded in ``docs/rewrite-status.md``: the outbound-link probe
skips this endpoint because it is POST-only, so nothing proved it existed. A
fake provider could only have confirmed what we already believed — and what we
believed was wrong, which is how the region came to be read from a product that
never returns one.

Read-only: every call looks up a public address and writes nothing anywhere.

**A 403 naming an IP address is not a code failure.** The key is IP-restricted
and this machine's egress address has been seen to change mid-session; check the
allowlist in the GCP project before reading anything into the error.
"""

import pytest

from apps.company.services.geocoding_service import fetch_place, search_places

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _credentials(integration_credentials: None) -> None:
    """Bring the Maps key across from the dev database (ADR 0050)."""


# A public address, chosen because its region and its city differ: Christchurch
# sits in "Canterbury Region", so a lookup that returned the city where the
# region belongs would pass against an Auckland address and fail here.
ADDRESS = "45 Sir William Pickering Drive, Burnside, Christchurch, New Zealand"


class TestSearch:
    def test_a_real_search_returns_a_region_and_its_subdivision(self) -> None:
        candidates = search_places(ADDRESS)

        assert candidates
        place = candidates[0]
        assert place.region == "Canterbury Region"
        assert place.nz_subdivision == "CAN"
        assert place.city == "Christchurch"
        assert place.country == "New Zealand"
        assert place.latitude is not None
        assert place.longitude is not None
        assert place.place_id != ""

    def test_the_whole_reply_is_kept(self) -> None:
        """The stored response must carry more than the fields read today."""
        place = search_places(ADDRESS)[0]

        assert {"viewport", "types", "postalAddress"} <= set(place.raw)

    def test_an_address_google_cannot_match_returns_nothing(self) -> None:
        assert search_places("qqqzzz nowhere at all 99999, New Zealand") == []


class TestFetchById:
    def test_a_picked_candidate_can_be_re_read_by_its_id(self) -> None:
        """The save path re-reads rather than trusting geo fields from a browser."""
        picked = search_places(ADDRESS)[0]

        refetched = fetch_place(picked.place_id)

        assert refetched is not None
        assert refetched.place_id == picked.place_id
        assert refetched.region == picked.region
        assert refetched.latitude == pytest.approx(picked.latitude)
        assert refetched.longitude == pytest.approx(picked.longitude)

    def test_a_unit_address_re_reads_too(self) -> None:
        """Google answers a subpremise with a long synthetic id, not a place id.

        It still fetches, which is what lets the save path use the id alone —
        checked live because the two id shapes are not documented as
        interchangeable.
        """
        picked = search_places("Unit 3, 41 Elizabeth Knox Place, Mt Wellington, Auckland")[0]

        refetched = fetch_place(picked.place_id)

        assert refetched is not None
        assert refetched.nz_subdivision == "AUK"
