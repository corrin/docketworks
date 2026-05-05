"""
API endpoint for CompanyDefaults schema/metadata.

Provides field metadata so frontend can dynamically render settings UI.
"""

import logging
from typing import Any

from django.db import models
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workflow.models import CompanyDefaults
from apps.workflow.models.settings_metadata import (
    COMPANY_DEFAULTS_FIELD_SECTIONS,
    COMPANY_DEFAULTS_READ_ONLY_FIELDS,
    SettingsSection,
    get_field_metadata,
)
from apps.workflow.serializers import CompanyDefaultsSchemaSerializer

logger = logging.getLogger(__name__)


class CompanyDefaultsSchemaAPIView(APIView):
    """
    API endpoint that returns field metadata for CompanyDefaults.

    This enables the frontend to dynamically render settings UI
    without hardcoding field definitions.

    GET /api/company-defaults/schema/

    Returns sections with their fields, ordered for UI display.
    Fields marked as 'internal' section are excluded from the response.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CompanyDefaultsSchemaSerializer},
        examples=[
            OpenApiExample(
                "Example Response",
                value={
                    "sections": [
                        {
                            "key": "general",
                            "title": "General Settings",
                            "order": 1,
                            "fields": [
                                {
                                    "key": "company_name",
                                    "label": "Company Name",
                                    "type": "text",
                                    "required": True,
                                    "help_text": "",
                                    "section": "general",
                                }
                            ],
                        }
                    ]
                },
            )
        ],
    )
    def get(self, request: Request) -> Response:
        """Return schema metadata for CompanyDefaults fields."""
        sections_dict: dict[str, dict[str, Any]] = {
            section_key: {
                "key": section_key,
                "title": title,
                "order": order,
                "fields": [],
            }
            for section_key, title, order in SettingsSection.all_sections()
            if section_key != "internal"
        }

        # Get all model fields
        model = CompanyDefaults
        for field in model._meta.get_fields():
            # Skip reverse relations and non-concrete fields
            if not isinstance(field, models.Field):
                continue

            field_name = field.name

            # Get section for this field. If a new field is added to the model
            # but the developer forgets to register it in
            # COMPANY_DEFAULTS_FIELD_SECTIONS, fall back to the default section
            # (the get_field_metadata helper itself defaults to "company") and
            # log a loud warning. The startup system check is the primary
            # enforcement; this fallback ensures the field still reaches the
            # UI even if checks are skipped or run late.
            section_key = COMPANY_DEFAULTS_FIELD_SECTIONS.get(field_name)
            if not section_key:
                logger.warning(
                    "CompanyDefaults field '%s' has no entry in "
                    "COMPANY_DEFAULTS_FIELD_SECTIONS; falling back to default "
                    "section. Add it to "
                    "apps/workflow/models/settings_metadata.py.",
                    field_name,
                )
                field_meta = get_field_metadata(
                    field, field_name, COMPANY_DEFAULTS_READ_ONLY_FIELDS
                )
                fallback = field_meta["section"]
                if fallback in sections_dict:
                    sections_dict[fallback]["fields"].append(field_meta)
                continue

            # Skip internal fields
            if section_key == "internal":
                continue

            # Add field metadata
            if section_key in sections_dict:
                field_meta = get_field_metadata(
                    field, field_name, COMPANY_DEFAULTS_READ_ONLY_FIELDS
                )
                sections_dict[section_key]["fields"].append(field_meta)

        # Convert to sorted list
        sections = sorted(sections_dict.values(), key=lambda s: s["order"])

        return Response({"sections": sections})
