"""Address validation and geocoding via the Google Address Validation API.

Ported verbatim from v1 ``apps/company/services/geocoding_service.py``.
Exposed by the ``companies_addresses_validate_create`` endpoint
(``/api/companies/addresses/validate/``).
"""

import logging
import os
from dataclasses import dataclass

import requests

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
    """Get the Google Maps API key from the environment.

    Raises:
        GeocodingNotConfiguredError: if GOOGLE_MAPS_API_KEY is unset.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise GeocodingNotConfiguredError("GOOGLE_MAPS_API_KEY not configured")
    return api_key


def geocode_address(address: str, api_key: str | None = None) -> GeocodingResult | None:
    """Geocode a freetext address using the Google Address Validation API.

    Args:
        address: Freetext address string to geocode.
        api_key: Optional API key (uses the environment variable if omitted).

    Returns:
        GeocodingResult with structured address data, or None if no result.

    Raises:
        GeocodingNotConfiguredError: if no API key is available.
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

    try:
        response = requests.post(
            url,
            json=payload,
            params={"key": api_key},
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
