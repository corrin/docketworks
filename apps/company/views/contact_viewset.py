"""
CompanyPersonLink ViewSet

ViewSet for CompanyPersonLink CRUD operations using DRF's ModelViewSet.
Provides list, create, retrieve, update, partial_update, and destroy actions.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets

from apps.company.models import CompanyPersonLink, ContactMethod
from apps.company.serializers import CompanyPersonLinkSerializer


class CompanyPersonLinkViewSet(viewsets.ModelViewSet):
    """
    ViewSet for CompanyPersonLink CRUD operations.

    Endpoints:
    - GET    /api/companies/person-links/       - list all company-person links
    - POST   /api/companies/person-links/       - create link
    - GET    /api/companies/person-links/<id>/  - retrieve link
    - PUT    /api/companies/person-links/<id>/  - full update
    - PATCH  /api/companies/person-links/<id>/  - partial update
    - DELETE /api/companies/person-links/<id>/  - soft delete (sets is_active=False)

    Query Parameters:
    - company_id: Filter links by company UUID
    """

    queryset = CompanyPersonLink.objects.filter(is_active=True)
    serializer_class = CompanyPersonLinkSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="company_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Filter links by company UUID",
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """List all company-person links, optionally filtered by company_id."""
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """
        Filter to only active links, optionally filtered by company_id.
        """
        queryset = (
            CompanyPersonLink.objects.filter(is_active=True)
            .select_related("person")
            .annotate(phone=ContactMethod.primary_phone_for_link_annotation())
        )
        company_id = self.request.query_params.get("company_id")
        if company_id:
            queryset = queryset.filter(company_id=company_id)
        return queryset.order_by("-is_primary", "person__name")

    def perform_destroy(self, instance):
        """
        Soft delete - set is_active=False instead of actually deleting.
        """
        instance.is_active = False
        instance.save(update_fields=["is_active"])
