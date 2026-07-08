"""
ClientContact ViewSet

ViewSet for ClientContact CRUD operations using DRF's ModelViewSet.
Provides list, create, retrieve, update, partial_update, and destroy actions.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets

from apps.company.models import ClientContact, ClientContactMethod
from apps.company.serializers import ClientContactSerializer


class ClientContactViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ClientContact CRUD operations.

    Endpoints:
    - GET    /api/companies/contacts/           - list all contacts
    - POST   /api/companies/contacts/           - create contact
    - GET    /api/companies/contacts/<id>/      - retrieve contact
    - PUT    /api/companies/contacts/<id>/      - full update
    - PATCH  /api/companies/contacts/<id>/      - partial update
    - DELETE /api/companies/contacts/<id>/      - soft delete (sets is_active=False)

    Query Parameters:
    - company_id: Filter contacts by company UUID
    """

    queryset = ClientContact.objects.filter(is_active=True)
    serializer_class = ClientContactSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="company_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Filter contacts by company UUID",
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """List all contacts, optionally filtered by company_id."""
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """
        Filter to only active contacts, optionally filtered by company_id.
        """
        queryset = ClientContact.objects.filter(is_active=True).annotate(
            phone=ClientContactMethod.primary_phone_annotation(
                owner="contact", outer_ref="pk"
            )
        )
        company_id = self.request.query_params.get("company_id")
        if company_id:
            queryset = queryset.filter(company_id=company_id)
        return queryset.order_by("-is_primary", "name")

    def perform_destroy(self, instance):
        """
        Soft delete - set is_active=False instead of actually deleting.
        """
        instance.is_active = False
        instance.save(update_fields=["is_active"])
