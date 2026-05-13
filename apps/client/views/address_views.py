"""
Address Validation Views

Provides address cleaning/validation using Google Address Validation API.
"""

import logging
from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.client.services.geocoding_service import (
    GeocodingError,
    GeocodingNotConfiguredError,
    geocode_address,
)
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class AddressValidateView(APIView):
    """
    Validate and clean an address using Google Address Validation API.

    POST /api/clients/addresses/validate/
    Body: {"address": "123 Main St Melbourne"}

    Returns candidate addresses with structured components.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "Freetext address to validate",
                    },
                },
                "required": ["address"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "formatted_address": {"type": "string"},
                                "street": {"type": "string"},
                                "suburb": {"type": "string"},
                                "city": {"type": "string"},
                                "state": {"type": "string"},
                                "postal_code": {"type": "string"},
                                "country": {"type": "string"},
                                "google_place_id": {"type": "string"},
                                "latitude": {"type": "number"},
                                "longitude": {"type": "number"},
                            },
                        },
                    },
                },
            },
            400: {"description": "Missing or invalid address"},
            503: {"description": "Google API unavailable or not configured"},
        },
    )
    def post(self, request: Request) -> Response:
        """Validate an address and return structured candidates."""
        address = request.data.get("address", "").strip()

        if not address:
            return Response(
                {"error": "Address is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = geocode_address(address)
            if result:
                return Response({"candidates": [asdict(result)]})
            return Response({"candidates": []})
        except GeocodingNotConfiguredError:
            logger.warning("GOOGLE_MAPS_API_KEY not configured")
            return Response(
                {"error": "Address validation service not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except GeocodingError as exc:
            persist_app_error(exc)
            logger.exception("Address validation failed")
            return Response(
                {"error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
