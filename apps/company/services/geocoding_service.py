"""Google address lookups: Address Validation for supplier entry, Places for the shop.

Two Google products, one credential, because they answer different questions.

``geocode_address`` calls **Address Validation** and backs the supplier-address
autocomplete (``companies_addresses_validate_create``,
``/api/companies/addresses/validate/``). It is the right product there: it
grades what a person typed, returning a verdict — granularity, completeness,
which components it had to infer.

``look_up_place`` calls **Places (New)** and backs the shop's own address. It
exists because Address Validation does not answer the question the KPI calendar
needs. Measured 2026-09-02 against six real NZ addresses across four regions:
Address Validation returns NO ``administrative_area_level_1`` for any of them,
so the region is simply absent from that product's reply. (The
``administrative_area_level_1`` entry in ``_COMPONENT_FIELDS`` below is
therefore dead for NZ, which is why almost every stored ``state`` is NULL.)

Places over the classic Geocoding API, which also carries the region: Geocoding
is GET-only and takes the key as a **query parameter**, and the fable on
``geocode_address`` explains why a key in a URL ends up in the database. Places
takes ``X-Goog-Api-Key``, so the same rule holds without a second mechanism to
scrub URLs out of exceptions.
"""

import logging
from dataclasses import dataclass

import requests
from holidays.countries.new_zealand import NewZealand

from apps.core.models import IntegrationSettings

logger = logging.getLogger(__name__)


@dataclass
class GeocodingResult:
    """Structured result from geocoding an address."""

    formatted_address: str
    street: str
    suburb: str
    city: str
    state: str
    postal_code: str
    country: str
    google_place_id: str
    latitude: float | None
    longitude: float | None


_COMPONENT_FIELDS = {
    "street_number": "street_number",
    "route": "route",
    "sublocality_level_1": "suburb",
    "locality": "city",
    "administrative_area_level_1": "state",
    "postal_code": "postal_code",
    "country": "country",
}


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


def geocode_address(address: str, api_key: str | None = None) -> GeocodingResult | None:
    """Geocode a freetext address using the Google Address Validation API.

    Args:
        address: Freetext address string to geocode.
        api_key: Optional API key (uses the environment variable if omitted).

    Returns:
        GeocodingResult with structured address data, or None if no result.

    Raises:
        GeocodingNotConfiguredError: if no API key is set.
        GeocodingError: if the API call fails.
    """
    if not api_key:
        api_key = get_api_key()

    url = "https://addressvalidation.googleapis.com/v1:validateAddress"

    payload = {
        "address": {
            "addressLines": [address],
            "regionCode": "NZ",  # Default to New Zealand
        },
        "enableUspsCass": False,
    }

    # Fable: the key travels in a header, never the query string. requests
    # puts the full URL into every RequestException message, and that message
    # is persisted as an AppError and logged — so `?key=` would write the
    # credential into the database on the first network blip.
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"X-Goog-Api-Key": api_key},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise GeocodingError(f"Network error: {exc}") from exc

    if response.status_code != 200:
        logger.error(
            "Google Address Validation API error: %s - %s",
            response.status_code,
            response.text,
        )
        detail = response.text
        raise GeocodingError(f"Google API returned {response.status_code}: {detail}")

    data: dict[str, object] = response.json()
    return _parse_validation_result(data)


def _parse_validation_result(data: dict[str, object]) -> GeocodingResult | None:
    """Parse a Google Address Validation API response into a GeocodingResult."""
    result = _dict(data.get("result"))
    address_obj = _dict(result.get("address"))
    geocode = _dict(result.get("geocode"))

    formatted = _str(address_obj.get("formattedAddress"))
    if not formatted:
        return None

    # Extract place ID and coordinates
    place_id = _str(geocode.get("placeId"))
    location = _dict(geocode.get("location"))
    latitude = _float_or_none(location.get("latitude"))
    longitude = _float_or_none(location.get("longitude"))

    # Extract components
    components: dict[str, str] = {}
    raw_components = address_obj.get("addressComponents")
    if isinstance(raw_components, list):
        for component in raw_components:
            comp = _dict(component)
            comp_type = _str(comp.get("componentType"))
            text = _str(_dict(comp.get("componentName")).get("text"))
            field = _COMPONENT_FIELDS.get(comp_type)
            if field:
                components[field] = text

    # Build street from number + route
    street_parts = []
    if components.get("street_number"):
        street_parts.append(components["street_number"])
    if components.get("route"):
        street_parts.append(components["route"])
    street = " ".join(street_parts)

    return GeocodingResult(
        formatted_address=formatted,
        street=street,
        suburb=components.get("suburb", ""),
        city=components.get("city", ""),
        state=components.get("state", ""),
        postal_code=components.get("postal_code", ""),
        country=components.get("country", "New Zealand"),
        google_place_id=place_id,
        latitude=latitude,
        longitude=longitude,
    )


#: Google names most NZ regions "<Name> Region" but Auckland plainly "Auckland"
#: (measured across six addresses, 2026-09-02). Strip the suffix and the
#: holidays package's own alias table does the mapping — including its Māori
#: names — rather than a second copy here that would drift from the library's
#: data every time it updates.
_REGION_SUFFIX = " Region"

#: Places bills by field mask, so this is the list of things we actually keep.
#: Widening it costs money on every lookup; narrowing it silently drops a field
#: from the stored response.
_PLACES_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.formattedAddress",
        "places.shortFormattedAddress",
        "places.addressComponents",
        "places.location",
        "places.viewport",
        "places.types",
        "places.postalAddress",
    )
)


@dataclass(frozen=True)
class PlaceLookup:
    """One Places answer, alongside the whole reply it was read from."""

    formatted_address: str
    place_id: str
    latitude: float | None
    longitude: float | None
    #: Google's own wording, e.g. "Canterbury Region" — kept verbatim so the
    #: stored value can be re-mapped if the holidays package renames a code.
    region: str
    #: The holidays-package subdivision, e.g. "CAN". None when Google named no
    #: region, or named one the package does not know.
    nz_subdivision: str | None
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


def look_up_place(address: str, api_key: str | None = None) -> PlaceLookup | None:
    """Resolve one freetext address through Places (New), keeping the whole reply.

    Returns None when Google matched nothing — a real outcome for a typo, and
    distinct from the errors raised below.
    """
    if not address:
        raise ValueError("Cannot look up an empty address")
    if not api_key:
        api_key = get_api_key()

    try:
        response = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            json={"textQuery": address, "regionCode": "NZ", "maxResultCount": 1},
            # Header auth, as on Address Validation above and for the same
            # reason: the classic Geocoding API would have put the key in the
            # query string, and requests copies the full URL into every
            # RequestException message that persist_app_error then stores.
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _PLACES_FIELD_MASK},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise GeocodingError(f"Network error: {exc}") from exc

    if response.status_code != 200:
        logger.error("Google Places API error: %s - %s", response.status_code, response.text)
        raise GeocodingError(f"Google Places returned {response.status_code}: {response.text}")

    return _parse_place_result(response.json())


def _parse_place_result(data: dict[str, object]) -> PlaceLookup | None:
    """Read the first Places match, or None when Google matched nothing."""
    places = data.get("places")
    if not isinstance(places, list) or not places:
        return None
    place = _dict(places[0])

    formatted = _str(place.get("formattedAddress"))
    if not formatted:
        return None

    location = _dict(place.get("location"))
    region = ""
    components = place.get("addressComponents")
    if isinstance(components, list):
        for component in components:
            entry = _dict(component)
            types = entry.get("types")
            if isinstance(types, list) and "administrative_area_level_1" in types:
                region = _str(entry.get("longText"))
                break

    return PlaceLookup(
        formatted_address=formatted,
        place_id=_str(place.get("id")),
        latitude=_float_or_none(location.get("latitude")),
        longitude=_float_or_none(location.get("longitude")),
        region=region,
        nz_subdivision=nz_subdivision_for_region(region),
        raw=place,
    )


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
