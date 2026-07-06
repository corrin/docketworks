"""
Geocoding Service

Provides address validation and geocoding using Google Address Validation API.
"""

import logging
import os
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class GeocodingResult:
    """Result from geocoding an address."""

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


class GeocodingError(Exception):
    """Raised when geocoding fails."""


class GeocodingNotConfiguredError(GeocodingError):
    """Raised when Google API key is not configured."""


def get_api_key() -> str:
    """Get the Google Maps API key from environment."""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise GeocodingNotConfiguredError("GOOGLE_MAPS_API_KEY not configured")
    return api_key


def geocode_address(address: str, api_key: str | None = None) -> GeocodingResult | None:
    """
    Geocode a freetext address using Google Address Validation API.

    Args:
        address: Freetext address string to geocode
        api_key: Optional API key (uses environment variable if not provided)

    Returns:
        GeocodingResult with structured address data, or None if no result

    Raises:
        GeocodingNotConfiguredError: If API key not available
        GeocodingError: If API call fails
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
            f"Google Address Validation API error: {response.status_code} - {response.text}"
        )
        detail = response.text
        raise GeocodingError(f"Google API returned {response.status_code}: {detail}")

    data = response.json()
    return _parse_validation_result(data)


def _parse_validation_result(data: dict) -> GeocodingResult | None:
    """Parse Google Address Validation API response into GeocodingResult."""
    result = data.get("result", {})
    address_obj = result.get("address", {})
    geocode = result.get("geocode", {})

    formatted = address_obj.get("formattedAddress", "")
    if not formatted:
        return None

    # Extract place ID and coordinates
    place_id = geocode.get("placeId", "")
    location = geocode.get("location", {})
    latitude = location.get("latitude")
    longitude = location.get("longitude")

    # Extract components
    components = {}
    for component in address_obj.get("addressComponents", []):
        comp_type = component.get("componentType", "")
        text = component.get("componentName", {}).get("text", "")

        if comp_type == "street_number":
            components["street_number"] = text
        elif comp_type == "route":
            components["route"] = text
        elif comp_type == "sublocality_level_1":
            components["suburb"] = text
        elif comp_type == "locality":
            components["city"] = text
        elif comp_type == "administrative_area_level_1":
            components["state"] = text
        elif comp_type == "postal_code":
            components["postal_code"] = text
        elif comp_type == "country":
            components["country"] = text

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
