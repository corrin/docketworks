"""
SupplierPickupAddress ViewSet

ViewSet for SupplierPickupAddress CRUD operations using DRF's ModelViewSet.
Provides list, create, retrieve, update, partial_update, and destroy actions.

These are delivery/pickup locations for suppliers (or any company).
Despite the name, addresses can be created for any company, not just suppliers.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets

from apps.company.models import SupplierPickupAddress
from apps.company.serializers import SupplierPickupAddressSerializer


class SupplierPickupAddressViewSet(viewsets.ModelViewSet):
    """
    ViewSet for SupplierPickupAddress CRUD operations.

    Endpoints:
    - GET    /api/companies/pickup-addresses/           - list all addresses
    - POST   /api/companies/pickup-addresses/           - create address
    - GET    /api/companies/pickup-addresses/<id>/      - retrieve address
    - PUT    /api/companies/pickup-addresses/<id>/      - full update
    - PATCH  /api/companies/pickup-addresses/<id>/      - partial update
    - DELETE /api/companies/pickup-addresses/<id>/      - soft delete (sets is_active=False)

    Query Parameters:
    - supplier_id: Filter addresses by supplier (company) UUID
    """

    queryset = SupplierPickupAddress.objects.filter(is_active=True)
    serializer_class = SupplierPickupAddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="supplier_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Filter addresses by supplier UUID",
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """List all pickup addresses, optionally filtered by supplier_id."""
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """
        Filter to only active addresses, optionally filtered by supplier_id.
        """
        queryset = SupplierPickupAddress.objects.filter(is_active=True)
        supplier_id = self.request.query_params.get("supplier_id")
        if supplier_id:
            queryset = queryset.filter(company_id=supplier_id)
        return queryset.order_by("-is_primary", "name")

    def perform_destroy(self, instance):
        """
        Soft delete - set is_active=False instead of actually deleting.
        """
        instance.is_active = False
        instance.save(update_fields=["is_active"])
