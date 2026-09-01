"""Google Places (New) address lookups — the one address lookup in this codebase.

Both the supplier-address autocomplete (``companies_addresses_validate_create``,
``/api/companies/addresses/validate/``) and the shop's own address come through
here.

Places rather than the Address Validation API this used to call. Measured
2026-09-02 against six real NZ addresses across four regions:
``v1:validateAddress`` returns no ``administrative_area_level_1`` for any of
them, so it cannot answer "which region is this business in" at all, and its
``administrative_area_level_1 -> state`` mapping had never once fired — which is
why 513 of 522 supplier ``state`` values were NULL. Address Validation does
grade what a person typed and return a verdict Places has no equivalent for;
that was not worth a second implementation of "look up an address" beside one
that answers strictly more.

Places rather than the classic Geocoding API, which also carries the region:
Geocoding is GET-only with the key as a **query parameter**, and ``requests``
copies the full URL into every ``RequestException`` message, which
``persist_app_error`` then writes to the database. Places takes
``X-Goog-Api-Key``, so a credential never enters a URL.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import requests
from holidays.countries.new_zealand import NewZealand

from apps.core.models import IntegrationSettings

logger = logging.getLogger(__name__)


class GeocodingError(Exception):
    """Raised when geocoding fails."""


class GeocodingNotConfiguredError(GeocodingError):
    """Raised when the Google API key is not configured."""


def get_api_key() -> str:
    """Return the Google Maps API key from IntegrationSettings.

    Raises:
        GeocodingNotConfiguredError: if the key is not set.
    """
    api_key = IntegrationSettings.get_solo().google_maps_api_key
    if api_key is None:
        raise GeocodingNotConfiguredError(
            "Google Maps API key not set — enter it on Admin > Integrations"
        )
    return api_key


#: Google names most NZ regions "<Name> Region" but Auckland plainly "Auckland"
#: (measured across six addresses, 2026-09-02). Strip the suffix and the
#: holidays package's own alias table does the mapping — including its Māori
#: names — rather than a second copy here that would drift from the library's
#: data every time it updates.
_REGION_SUFFIX = " Region"

#: Places bills by field mask, so this is the list of things we actually keep.
#: Widening it costs money on every lookup; narrowing it silently drops a field
#: from the stored response.
_PLACE_FIELDS = (
    "id",
    "formattedAddress",
    "shortFormattedAddress",
    "addressComponents",
    "location",
    "viewport",
    "types",
    "postalAddress",
)

#: searchText returns a list, so its mask names the repeated field; places.get
#: returns the resource itself and takes the bare names.
_SEARCH_FIELD_MASK = ",".join(f"places.{name}" for name in _PLACE_FIELDS)
_GET_FIELD_MASK = ",".join(_PLACE_FIELDS)

#: Enough for a person to recognise their own address among near
#: neighbours, few enough that a debounced keystroke stays cheap.
_CANDIDATE_LIMIT = 5


@dataclass(frozen=True)
class PlaceLookup:
    """One Places answer, alongside the whole reply it was read from."""

    formatted_address: str
    street: str
    suburb: str
    city: str
    #: Google's own wording, e.g. "Canterbury Region" — kept verbatim so the
    #: stored value can be re-mapped if the holidays package renames a code.
    region: str
    #: The holidays-package subdivision, e.g. "CAN". None when Google named no
    #: region, or named one the package does not know.
    nz_subdivision: str | None
    postal_code: str
    country: str
    place_id: str
    latitude: float | None
    longitude: float | None
    #: The whole reply. Kept because re-fetching a field already paid for is
    #: the failure mode, and because the confidence and geometry Google sends
    #: have no column of their own yet.
    raw: dict[str, object]


def nz_subdivision_for_region(region: str) -> str | None:
    """Map Google's region wording to the subdivision code ``holidays`` uses.

    None rather than a raise: a region Google names and the package does not
    know is a coverage gap, not a broken install, and the caller stores the
    verbatim ``region`` either way.

    Cannot distinguish South Canterbury, which ``holidays`` carries as its own
    subdivision with its own anniversary day: Google answers "Canterbury
    Region" for Timaru exactly as it does for Christchurch. A South Canterbury
    business needs the subdivision set by hand.
    """
    if not region:
        return None
    aliases: dict[str, str] = NewZealand.subdivisions_aliases
    return aliases.get(region.removesuffix(_REGION_SUFFIX)) or aliases.get(region)


def search_places(
    address: str, *, limit: int = _CANDIDATE_LIMIT, api_key: str | None = None
) -> list[PlaceLookup]:
    """Offer the candidates a person picks from, best match first.

    A list rather than one answer because the caller is a picker: the operator
    confirms which address Google found, which is how they see "Mt Wellington"
    become "St Johns" instead of having it substituted underneath them.

    An empty list is a real outcome — a typo matches nothing — and is distinct
    from the errors raised below.
    """
    if not address:
        raise ValueError("Cannot look up an empty address")
    if not api_key:
        api_key = get_api_key()

    payload = {"textQuery": address, "regionCode": "NZ", "maxResultCount": limit}
    data = _places_call(
        lambda: requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            json=payload,
            # Header auth, as on Address Validation above and for the same
            # reason: the classic Geocoding API would have put the key in the
            # query string, and requests copies the full URL into every
            # RequestException message that persist_app_error then stores.
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _SEARCH_FIELD_MASK},
            timeout=10,
        )
    )
    places = data.get("places")
    if not isinstance(places, list):
        return []
    found = (_place_from_payload(_dict(place)) for place in places)
    return [place for place in found if place is not None]


def fetch_place(place_id: str, api_key: str | None = None) -> PlaceLookup | None:
    """Re-read one place by the id a person already picked.

    The save path uses this rather than storing the coordinates the browser
    posted back: the id is the only part of a chosen candidate a client cannot
    quietly swap for a different location, and re-reading is also what puts the
    whole reply in our hands to store.
    """
    if not place_id:
        raise ValueError("Cannot fetch an empty place id")
    if not api_key:
        api_key = get_api_key()

    data = _places_call(
        lambda: requests.get(
            f"https://places.googleapis.com/v1/places/{place_id}",
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _GET_FIELD_MASK},
            timeout=10,
        )
    )
    return _place_from_payload(data)


def _places_call(send: Callable[[], requests.Response]) -> dict[str, object]:
    """Run one Places request, converting its two failure shapes."""
    try:
        response = send()
    except requests.RequestException as exc:
        raise GeocodingError(f"Network error: {exc}") from exc

    if response.status_code != 200:
        logger.error("Google Places API error: %s - %s", response.status_code, response.text)
        raise GeocodingError(f"Google Places returned {response.status_code}: {response.text}")

    parsed: dict[str, object] = response.json()
    return parsed


def _place_from_payload(place: dict[str, object]) -> PlaceLookup | None:
    """Read one place, whether it came from a search or a fetch by id."""
    formatted = _str(place.get("formattedAddress"))
    if not formatted:
        return None

    components = _components_by_type(place.get("addressComponents"))
    region = components.get("administrative_area_level_1", "")
    location = _dict(place.get("location"))
    postal = _dict(place.get("postalAddress"))

    return PlaceLookup(
        formatted_address=formatted,
        street=_street(postal, components),
        suburb=components.get("sublocality_level_1", ""),
        city=components.get("locality", ""),
        region=region,
        nz_subdivision=nz_subdivision_for_region(region),
        postal_code=components.get("postal_code", ""),
        country=components.get("country", ""),
        place_id=_str(place.get("id")),
        latitude=_float_or_none(location.get("latitude")),
        longitude=_float_or_none(location.get("longitude")),
        raw=place,
    )


def _components_by_type(raw: object) -> dict[str, str]:
    """Index a place's components by type.

    Places gives each component a LIST of types (``["locality", "political"]``)
    where Address Validation gave one string, so a component lands under every
    type it claims. Reading it as a single value is the mistake that makes a
    parser written against the older product return empty strings in silence.
    """
    indexed: dict[str, str] = {}
    if not isinstance(raw, list):
        return indexed
    for component in raw:
        entry = _dict(component)
        types = entry.get("types")
        if not isinstance(types, list):
            continue
        text = _str(entry.get("longText"))
        for component_type in types:
            if isinstance(component_type, str):
                indexed.setdefault(component_type, text)
    return indexed


def _street(postal: dict[str, object], components: dict[str, str]) -> str:
    """Google's own street line, falling back to rebuilding it.

    ``postalAddress.addressLines`` already reads "3/41 Elizabeth Knox Place" —
    rebuilding from ``street_number`` and ``route`` drops the unit, because the
    unit is a separate ``subpremise`` component. Preferred for that reason.
    """
    lines = postal.get("addressLines")
    if isinstance(lines, list) and lines:
        first = _str(lines[0])
        if first:
            return first
    parts = [components.get("street_number", ""), components.get("route", "")]
    return " ".join(part for part in parts if part)


def _dict(value: object) -> dict[str, object]:
    """Narrow an untrusted JSON member to a dict ({} otherwise)."""
    return value if isinstance(value, dict) else {}


def _str(value: object) -> str:
    """Narrow an untrusted JSON member to a str ("" otherwise)."""
    return value if isinstance(value, str) else ""


def _float_or_none(value: object) -> float | None:
    """Narrow an untrusted JSON member to a float (None otherwise)."""
    if isinstance(value, int | float):
        return float(value)
    return None
