"""
ClientContact ViewSet

ViewSet for ClientContact CRUD operations using DRF's ModelViewSet.
Provides list, create, retrieve, update, partial_update, and destroy actions.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets

from apps.client.models import ClientContact, ClientContactMethod
from apps.client.serializers import ClientContactSerializer


class ClientContactViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ClientContact CRUD operations.

    Endpoints:
    - GET    /api/clients/contacts/           - list all contacts
    - POST   /api/clients/contacts/           - create contact
    - GET    /api/clients/contacts/<id>/      - retrieve contact
    - PUT    /api/clients/contacts/<id>/      - full update
    - PATCH  /api/clients/contacts/<id>/      - partial update
    - DELETE /api/clients/contacts/<id>/      - soft delete (sets is_active=False)

    Query Parameters:
    - client_id: Filter contacts by client UUID
    """

    queryset = ClientContact.objects.filter(is_active=True)
    serializer_class = ClientContactSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="client_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Filter contacts by client UUID",
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """List all contacts, optionally filtered by client_id."""
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """
        Filter to only active contacts, optionally filtered by client_id.
        """
        queryset = ClientContact.objects.filter(is_active=True).annotate(
            phone=ClientContactMethod.primary_phone_annotation(
                owner="contact", outer_ref="pk"
            )
        )
        client_id = self.request.query_params.get("client_id")
        if client_id:
            queryset = queryset.filter(client_id=client_id)
        return queryset.order_by("-is_primary", "name")

    def perform_destroy(self, instance):
        """
        Soft delete - set is_active=False instead of actually deleting.
        """
        instance.is_active = False
        instance.save(update_fields=["is_active"])
