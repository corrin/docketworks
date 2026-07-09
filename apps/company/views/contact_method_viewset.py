"""Company/person contact method ViewSet."""

from typing import cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets
from rest_framework.serializers import BaseSerializer

from apps.company.models import ContactMethod
from apps.company.serializers import ContactMethodSerializer
from apps.crm.tasks import rematch_phone_calls_task
from apps.workflow.api.pagination import PageSizePagination


def _phone_number_for_rematch(method: ContactMethod | None) -> str | None:
    if method is None:
        return None
    if method.method_type != ContactMethod.MethodType.PHONE:
        return None
    normalized = method.normalized_value
    if normalized:
        return normalized
    return ContactMethod.normalize_phone(method.value)


class ContactMethodViewSet(viewsets.ModelViewSet):
    """CRUD API for canonical company/person phone and email methods."""

    serializer_class = ContactMethodSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PageSizePagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="company_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name="person_id",
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
        queryset = ContactMethod.objects.select_related(
            "company",
            "person",
        )
        company_id = self.request.query_params.get("company_id")
        if company_id:
            queryset = queryset.filter(company_id=company_id) | queryset.filter(
                person__company_links__company_id=company_id
            )

        person_id = self.request.query_params.get("person_id")
        if person_id:
            queryset = queryset.filter(person_id=person_id)

        method_type = self.request.query_params.get("method_type")
        if method_type:
            queryset = queryset.filter(method_type=method_type)

        return queryset.distinct().order_by("method_type", "-is_primary", "value")

    def perform_create(self, serializer: BaseSerializer[ContactMethod]) -> None:
        method = serializer.save()
        phone_number = _phone_number_for_rematch(method)
        if phone_number:
            rematch_phone_calls_task.delay([phone_number])

    def perform_update(self, serializer: BaseSerializer[ContactMethod]) -> None:
        old_method = cast(ContactMethod, self.get_object())
        old_phone_number = _phone_number_for_rematch(old_method)
        method = serializer.save()
        new_phone_number = _phone_number_for_rematch(method)
        phone_numbers = [
            number for number in [old_phone_number, new_phone_number] if number
        ]
        if phone_numbers:
            rematch_phone_calls_task.delay(phone_numbers)

    def perform_destroy(self, instance: ContactMethod) -> None:
        phone_number = _phone_number_for_rematch(instance)
        instance.delete()
        if phone_number:
            rematch_phone_calls_task.delay([phone_number])
