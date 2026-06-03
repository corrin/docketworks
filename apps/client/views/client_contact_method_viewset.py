"""Client/contact contact method ViewSet."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets

from apps.client.models import ClientContactMethod
from apps.client.serializers import ClientContactMethodSerializer


class ClientContactMethodViewSet(viewsets.ModelViewSet):
    """CRUD API for canonical client/contact phone and email methods."""

    serializer_class = ClientContactMethodSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="client_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name="contact_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name="method_type",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = ClientContactMethod.objects.select_related(
            "client",
            "contact",
            "contact__client",
        )
        client_id = self.request.query_params.get("client_id")
        if client_id:
            queryset = queryset.filter(client_id=client_id) | queryset.filter(
                contact__client_id=client_id
            )

        contact_id = self.request.query_params.get("contact_id")
        if contact_id:
            queryset = queryset.filter(contact_id=contact_id)

        method_type = self.request.query_params.get("method_type")
        if method_type:
            queryset = queryset.filter(method_type=method_type)

        return queryset.distinct().order_by("method_type", "-is_primary", "value")
