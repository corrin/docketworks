"""First-class Person directory, relationship, and contact-method APIs."""

from typing import cast

from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.person_serializers import (
    CompanyLinkWriteSerializer,
    CompanyPersonCreateSerializer,
    CompanyPersonSerializer,
    PersonCompanyLinkSerializer,
    PersonContactMethodWriteSerializer,
    PersonDetailSerializer,
    PersonIdentityUpdateSerializer,
    PersonSummarySerializer,
    PhoneOwnershipConflictSerializer,
    PhoneOwnershipRequestSerializer,
    PhoneOwnershipSerializer,
)
from apps.company.serializers import ContactMethodSerializer
from apps.company.services.person_service import (
    CompanyLinkData,
    NewPersonData,
    PersonCompanyLinkData,
    PersonDirectoryService,
    PersonPhoneConflictError,
    classify_phone_ownership,
    create_person_for_company,
    put_company_link,
    remove_company_link,
)
from apps.crm.tasks import rematch_phone_calls_task
from apps.job.permissions import IsOfficeStaff
from apps.workflow.api.pagination import PageSizePagination

PERSON_PERMISSIONS = [permissions.IsAuthenticated, IsOfficeStaff]


class PersonListView(generics.ListAPIView[Person]):
    """List and search active people across company relationships."""

    serializer_class = PersonSummarySerializer
    permission_classes = PERSON_PERMISSIONS
    pagination_class = PageSizePagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="q",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Search people by name, email, phone, or company.",
            )
        ]
    )
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Person]:
        return PersonDirectoryService.search(self.request.query_params.get("q", ""))


class PersonDetailView(generics.RetrieveUpdateAPIView[Person]):
    """Retrieve or update a Person's identity fields."""

    queryset = Person.objects.filter(is_active=True)
    permission_classes = PERSON_PERMISSIONS
    lookup_url_kwarg = "person_id"

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Person]]:
        if self.request.method in {"PUT", "PATCH"}:
            return PersonIdentityUpdateSerializer
        return PersonDetailSerializer

    def update(self, request: Request, *args: object, **kwargs: object) -> Response:
        super().update(request, *args, **kwargs)
        person = self.get_object()
        return Response(PersonDetailSerializer(person).data)


class CompanyPeopleView(APIView):
    """List a company's people or create a Person with its initial link."""

    permission_classes = PERSON_PERMISSIONS

    @extend_schema(responses={200: CompanyPersonSerializer(many=True)})
    def get(self, request: Request, company_id: str) -> Response:
        company = get_object_or_404(Company, id=company_id)
        links = (
            CompanyPersonLink.objects.filter(company=company, is_active=True)
            .select_related("person")
            .annotate(phone=ContactMethod.primary_phone_for_link_annotation())
            .order_by("-is_primary", "person__name")
        )
        return Response(CompanyPersonSerializer(links, many=True).data)

    @extend_schema(
        request=CompanyPersonCreateSerializer,
        responses={
            201: CompanyPersonSerializer,
            409: PhoneOwnershipConflictSerializer,
        },
    )
    def post(self, request: Request, company_id: str) -> Response:
        company = get_object_or_404(Company, id=company_id)
        payload = CompanyPersonCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = cast(NewPersonData, payload.validated_data)
        try:
            link = create_person_for_company(company=company, data=data)
        except PersonPhoneConflictError as exc:
            response = PhoneOwnershipConflictSerializer(data=exc.ownership)
            response.is_valid(raise_exception=True)
            return Response(response.data, status=status.HTTP_409_CONFLICT)
        link = (
            CompanyPersonLink.objects.select_related("person")
            .annotate(phone=ContactMethod.primary_phone_for_link_annotation())
            .get(pk=link.pk)
        )
        return Response(
            CompanyPersonSerializer(link).data, status=status.HTTP_201_CREATED
        )


class CompanyPersonPhoneOwnershipView(APIView):
    """Classify a phone before creating a Person for a company."""

    permission_classes = PERSON_PERMISSIONS

    @extend_schema(
        request=PhoneOwnershipRequestSerializer,
        responses={200: PhoneOwnershipSerializer},
    )
    def post(self, request: Request, company_id: str) -> Response:
        company = get_object_or_404(Company, id=company_id)
        payload = PhoneOwnershipRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = classify_phone_ownership(
            company=company, raw_phone=payload.validated_data["phone"]
        )
        return Response(PhoneOwnershipSerializer(result).data)


class PersonCompanyLinksView(APIView):
    """List all active company relationships for a Person."""

    permission_classes = PERSON_PERMISSIONS

    @extend_schema(responses={200: PersonCompanyLinkSerializer(many=True)})
    def get(self, request: Request, person_id: str) -> Response:
        person = get_object_or_404(Person, id=person_id, is_active=True)
        links = PersonDirectoryService.company_links(person)
        return Response(PersonCompanyLinkSerializer(links, many=True).data)


class PersonCompanyLinkDetailView(APIView):
    """Create, update, reactivate, or remove a Person-company relationship."""

    permission_classes = PERSON_PERMISSIONS

    @extend_schema(
        request=CompanyLinkWriteSerializer,
        responses={200: PersonCompanyLinkSerializer},
    )
    def put(self, request: Request, person_id: str, company_id: str) -> Response:
        person = get_object_or_404(Person, id=person_id, is_active=True)
        company = get_object_or_404(Company, id=company_id)
        payload = CompanyLinkWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        link = put_company_link(
            person=person,
            company=company,
            data=cast(CompanyLinkData, payload.validated_data),
        )
        response_data: PersonCompanyLinkData = {
            "company_id": str(link.company_id),
            "company_name": company.name,
            "position": link.position,
            "is_primary": link.is_primary,
            "notes": link.notes,
            "is_active": link.is_active,
        }
        return Response(PersonCompanyLinkSerializer(response_data).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, person_id: str, company_id: str) -> Response:
        person = get_object_or_404(Person, id=person_id, is_active=True)
        company = get_object_or_404(Company, id=company_id)
        try:
            remove_company_link(person=person, company=company)
        except ValueError as exc:
            raise ValidationError({"company_link": [str(exc)]}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


def _schedule_contact_method_rematch(method: ContactMethod) -> None:
    if method.method_type != ContactMethod.MethodType.PHONE:
        return
    normalized = method.normalized_value
    transaction.on_commit(lambda: rematch_phone_calls_task.delay([normalized]))


class PersonContactMethodsView(APIView):
    """List or create a Person's contact methods."""

    permission_classes = PERSON_PERMISSIONS

    @extend_schema(responses={200: ContactMethodSerializer(many=True)})
    def get(self, request: Request, person_id: str) -> Response:
        person = get_object_or_404(Person, id=person_id, is_active=True)
        methods = person.contact_methods.order_by(
            "method_type", "-is_primary", "label", "value"
        )
        return Response(ContactMethodSerializer(methods, many=True).data)

    @extend_schema(
        request=PersonContactMethodWriteSerializer,
        responses={201: ContactMethodSerializer},
    )
    def post(self, request: Request, person_id: str) -> Response:
        person = get_object_or_404(Person, id=person_id, is_active=True)
        payload = PersonContactMethodWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        serializer = ContactMethodSerializer(
            data={
                **payload.validated_data,
                "company": None,
                "person": str(person.id),
                "source": ContactMethod.Source.LOCAL,
            }
        )
        serializer.is_valid(raise_exception=True)
        method = serializer.save()
        _schedule_contact_method_rematch(method)
        return Response(
            ContactMethodSerializer(method).data, status=status.HTTP_201_CREATED
        )


class PersonContactMethodDetailView(APIView):
    """Update or delete one Person contact method."""

    permission_classes = PERSON_PERMISSIONS

    @extend_schema(
        request=PersonContactMethodWriteSerializer,
        responses={200: ContactMethodSerializer},
    )
    def patch(self, request: Request, person_id: str, method_id: str) -> Response:
        method = get_object_or_404(ContactMethod, id=method_id, person_id=person_id)
        payload = PersonContactMethodWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        serializer = ContactMethodSerializer(
            method, data=payload.validated_data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        old_normalized = method.normalized_value
        updated = serializer.save()
        if updated.method_type == ContactMethod.MethodType.PHONE:
            numbers = sorted({old_normalized, updated.normalized_value})
            transaction.on_commit(lambda: rematch_phone_calls_task.delay(numbers))
        return Response(ContactMethodSerializer(updated).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, person_id: str, method_id: str) -> Response:
        method = get_object_or_404(ContactMethod, id=method_id, person_id=person_id)
        normalized = method.normalized_value
        is_phone = method.method_type == ContactMethod.MethodType.PHONE
        method.delete()
        if is_phone:
            transaction.on_commit(lambda: rematch_phone_calls_task.delay([normalized]))
        return Response(status=status.HTTP_204_NO_CONTENT)
