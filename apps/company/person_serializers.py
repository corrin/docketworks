"""API contracts for first-class People and their company relationships."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.company.models import CompanyPersonLink, ContactMethod, Person
from apps.company.services.person_service import (
    PersonCompanyLinkData,
    PersonDirectoryService,
    PhoneCompanyOwner,
    PhoneOwnershipResult,
    PhonePersonMatch,
)


class PersonCompanyLinkSerializer(
    serializers.Serializer[PersonCompanyLinkData | list[PersonCompanyLinkData]]
):
    company_id = serializers.UUIDField()
    company_name = serializers.CharField()
    position = serializers.CharField(allow_null=True)
    is_primary = serializers.BooleanField()
    notes = serializers.CharField(allow_null=True)
    is_active = serializers.BooleanField()


class PersonCompanySummarySerializer(serializers.Serializer[dict[str, str]]):
    company_id = serializers.UUIDField()
    company_name = serializers.CharField()


class PersonSummarySerializer(serializers.ModelSerializer[Person]):
    primary_phone = serializers.SerializerMethodField()
    companies = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ["id", "name", "email", "primary_phone", "companies"]

    def get_primary_phone(self, person: Person) -> str:
        if "primary_phone" in person.__dict__:
            return str(person.__dict__["primary_phone"])
        method = (
            person.contact_methods.filter(method_type=ContactMethod.MethodType.PHONE)
            .order_by("-is_primary", "label", "value")
            .first()
        )
        return method.value if method else ""

    @extend_schema_field(PersonCompanySummarySerializer(many=True))
    def get_companies(self, person: Person) -> list[dict[str, str]]:
        return [
            {
                "company_id": link["company_id"],
                "company_name": link["company_name"],
            }
            for link in sorted(
                (
                    link
                    for link in PersonDirectoryService.company_links(person)
                    if link["is_active"]
                ),
                key=lambda link: link["company_name"],
            )
        ]


class PersonDetailSerializer(PersonSummarySerializer):
    company_links = serializers.SerializerMethodField()

    class Meta(PersonSummarySerializer.Meta):
        fields = [
            "id",
            "name",
            "email",
            "is_active",
            "created_at",
            "updated_at",
            "primary_phone",
            "companies",
            "company_links",
        ]

    @extend_schema_field(PersonCompanyLinkSerializer(many=True))
    def get_company_links(self, person: Person) -> list[PersonCompanyLinkData]:
        return list(PersonDirectoryService.company_links(person))


class PersonIdentityUpdateSerializer(serializers.ModelSerializer[Person]):
    class Meta:
        model = Person
        fields = ["name", "email"]
        extra_kwargs = {
            "name": {"required": False},
            "email": {
                "required": False,
                "allow_blank": True,
                "allow_null": True,
            },
        }


class CompanyPersonSerializer(serializers.ModelSerializer[CompanyPersonLink]):
    person_id = serializers.UUIDField(source="person.id", read_only=True)
    person_name = serializers.CharField(source="person.name", read_only=True)
    person_email = serializers.EmailField(
        source="person.email", read_only=True, allow_null=True
    )
    primary_phone = serializers.CharField(source="phone", read_only=True)

    class Meta:
        model = CompanyPersonLink
        fields = [
            "person_id",
            "person_name",
            "person_email",
            "primary_phone",
            "position",
            "is_primary",
            "notes",
        ]


class CompanyPersonCreateSerializer(serializers.Serializer[None]):
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    position = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255
    )
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_primary = serializers.BooleanField(required=False, default=False)

    def validate_phone(self, value: str | None) -> str | None:
        if value and not ContactMethod.normalize_phone(value):
            raise serializers.ValidationError(
                "Phone number must contain at least one digit"
            )
        return value


class CompanyLinkWriteSerializer(serializers.Serializer[None]):
    position = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255, default=None
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    is_primary = serializers.BooleanField(required=False, default=False)


class PhoneOwnershipRequestSerializer(serializers.Serializer[None]):
    phone = serializers.CharField()

    def validate_phone(self, value: str) -> str:
        if not ContactMethod.normalize_phone(value):
            raise serializers.ValidationError(
                "Phone number must contain at least one digit"
            )
        return value


class PhonePersonMatchSerializer(serializers.Serializer[PhonePersonMatch]):
    person_id = serializers.UUIDField()
    person_name = serializers.CharField()
    person_email = serializers.EmailField(allow_null=True)
    company_links = PersonCompanyLinkSerializer(many=True)


class PhoneCompanyOwnerSerializer(serializers.Serializer[PhoneCompanyOwner]):
    company_id = serializers.UUIDField()
    company_name = serializers.CharField()


class PhoneOwnershipSerializer(serializers.Serializer[PhoneOwnershipResult]):
    status = serializers.ChoiceField(
        choices=["available", "people", "company", "internal"]
    )
    normalized_phone = serializers.CharField()
    can_create_person = serializers.BooleanField()
    people = PhonePersonMatchSerializer(many=True)
    companies = PhoneCompanyOwnerSerializer(many=True)


class PhoneOwnershipConflictSerializer(PhoneOwnershipSerializer):
    pass


class PersonContactMethodWriteSerializer(serializers.Serializer[None]):
    method_type = serializers.ChoiceField(choices=ContactMethod.MethodType.choices)
    value = serializers.CharField(max_length=255)
    is_primary = serializers.BooleanField(required=False, default=False)

    def get_fields(self) -> dict[str, "serializers.Field[Any, Any, Any, Any]"]:
        fields = super().get_fields()
        fields["label"] = serializers.CharField(
            required=False, allow_blank=True, default=""
        )
        return fields
