"""Client/contact contact method ViewSet."""

from typing import cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets
from rest_framework.serializers import BaseSerializer

from apps.client.models import ClientContactMethod
from apps.client.serializers import ClientContactMethodSerializer
from apps.crm.services.phone_call_service import rematch_calls_for_numbers
from apps.workflow.api.pagination import PageSizePagination


def _phone_number_for_rematch(method: ClientContactMethod | None) -> str | None:
    if method is None:
        return None
    if method.method_type != ClientContactMethod.MethodType.PHONE:
        return None
    normalized = method.normalized_value
    if normalized:
        return normalized
    return ClientContactMethod.normalize_phone(method.value)


class ClientContactMethodViewSet(viewsets.ModelViewSet):
    """CRUD API for canonical client/contact phone and email methods."""

    serializer_class = ClientContactMethodSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PageSizePagination

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
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name="page_size",
                type=OpenApiTypes.INT,
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

    def perform_create(self, serializer: BaseSerializer[ClientContactMethod]) -> None:
        method = serializer.save()
        phone_number = _phone_number_for_rematch(method)
        if phone_number:
            rematch_calls_for_numbers([phone_number])

    def perform_update(self, serializer: BaseSerializer[ClientContactMethod]) -> None:
        old_method = cast(ClientContactMethod, self.get_object())
        old_phone_number = _phone_number_for_rematch(old_method)
        method = serializer.save()
        new_phone_number = _phone_number_for_rematch(method)
        phone_numbers = [
            number for number in [old_phone_number, new_phone_number] if number
        ]
        if phone_numbers:
            rematch_calls_for_numbers(phone_numbers)

    def perform_destroy(self, instance: ClientContactMethod) -> None:
        phone_number = _phone_number_for_rematch(instance)
        instance.delete()
        if phone_number:
            rematch_calls_for_numbers([phone_number])
