"""First-class Person directory and company-relationship operations."""

from typing import NotRequired, TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch, Q, QuerySet

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.workflow.services.error_persistence import persist_app_error


class PersonCompanyLinkData(TypedDict):
    company_id: str
    company_name: str
    position: str | None
    is_primary: bool
    notes: str | None
    is_active: bool


class PhonePersonMatch(TypedDict):
    person_id: str
    person_name: str
    person_email: str | None
    company_links: list[PersonCompanyLinkData]


class PhoneCompanyOwner(TypedDict):
    company_id: str
    company_name: str


class PhoneOwnershipResult(TypedDict):
    status: str
    normalized_phone: str
    can_create_person: bool
    people: list[PhonePersonMatch]
    companies: list[PhoneCompanyOwner]


class NewPersonData(TypedDict):
    name: str
    email: NotRequired[str | None]
    phone: NotRequired[str | None]
    position: NotRequired[str | None]
    notes: NotRequired[str | None]
    is_primary: NotRequired[bool]


class CompanyLinkData(TypedDict):
    position: str | None
    notes: str | None
    is_primary: bool


class PersonPhoneConflictError(Exception):
    def __init__(self, ownership: PhoneOwnershipResult) -> None:
        self.ownership = ownership
        super().__init__("Phone number is already owned by another CRM record")


class PersonDirectoryService:
    @staticmethod
    def search(query: str, *, include_archived: bool = False) -> QuerySet[Person]:
        base = (
            Person.objects.all()
            if include_archived
            else Person.objects.filter(is_active=True)
        )
        people = base.annotate(
            primary_phone=ContactMethod.primary_phone_annotation(
                owner="person", outer_ref="pk"
            )
        ).prefetch_related(
            Prefetch(
                "company_links",
                queryset=CompanyPersonLink.objects.filter(
                    is_active=True
                ).select_related("company"),
            )
        )
        search = query.strip()
        if not search:
            return people.order_by("name", "id")

        normalized_phone = ContactMethod.normalize_phone(search)
        filters = (
            Q(name__icontains=search)
            | Q(email__icontains=search)
            | Q(
                company_links__is_active=True,
                company_links__company__name__icontains=search,
            )
        )
        if normalized_phone:
            filters |= Q(
                contact_methods__method_type=ContactMethod.MethodType.PHONE,
                contact_methods__normalized_value__contains=normalized_phone.lstrip(
                    "+"
                ),
            )
        return people.filter(filters).distinct().order_by("name", "id")

    @staticmethod
    def company_links(person: Person) -> list[PersonCompanyLinkData]:
        prefetched = getattr(person, "_prefetched_objects_cache", {}).get(
            "company_links"
        )
        if prefetched is None:
            links = list(
                CompanyPersonLink.objects.filter(person=person).select_related(
                    "company"
                )
            )
        else:
            links = list(person.company_links.all())
        links.sort(
            key=lambda link: (
                not link.is_active,
                not link.is_primary,
                link.company.name,
            )
        )
        return [
            {
                "company_id": str(link.company_id),
                "company_name": link.company.name,
                "position": link.position,
                "is_primary": link.is_primary,
                "notes": link.notes,
                "is_active": link.is_active,
            }
            for link in links
        ]


def classify_phone_ownership(
    *, company: Company, raw_phone: str
) -> PhoneOwnershipResult:
    normalized = ContactMethod.normalize_phone(raw_phone)
    if not normalized:
        raise ValueError("Phone number must contain at least one digit")

    from apps.crm.models import PhoneEndpoint

    if PhoneEndpoint.objects.filter(
        normalized_number=normalized, is_active=True
    ).exists():
        return {
            "status": "internal",
            "normalized_phone": normalized,
            "can_create_person": False,
            "people": [],
            "companies": [],
        }

    methods = list(
        ContactMethod.objects.filter(
            method_type=ContactMethod.MethodType.PHONE,
            normalized_value=normalized,
        )
        .select_related("company", "person")
        .prefetch_related(
            Prefetch(
                "person__company_links",
                queryset=CompanyPersonLink.objects.select_related("company"),
            )
        )
        .order_by("id")
    )
    people_by_id: dict[UUID, PhonePersonMatch] = {}
    companies_by_id: dict[UUID, PhoneCompanyOwner] = {}
    for method in methods:
        if method.person_id is not None:
            person = method.person
            if person is None or not person.is_active:
                continue
            people_by_id.setdefault(
                person.id,
                {
                    "person_id": str(person.id),
                    "person_name": person.name,
                    "person_email": person.email,
                    "company_links": PersonDirectoryService.company_links(person),
                },
            )
        elif method.company_id is not None:
            owner = method.company
            if owner is None:
                raise RuntimeError(f"Contact method {method.id} has no company")
            companies_by_id.setdefault(
                owner.id,
                {"company_id": str(owner.id), "company_name": owner.name},
            )
        else:
            raise RuntimeError(f"Contact method {method.id} has no owner")

    conflict = ContactMethod.conflicting_company(normalized, {company.id})
    people = sorted(people_by_id.values(), key=lambda row: row["person_name"])
    companies = sorted(companies_by_id.values(), key=lambda row: row["company_name"])
    if people:
        status = "people"
    elif conflict is not None:
        status = "company"
    else:
        status = "available"
    return {
        "status": status,
        "normalized_phone": normalized,
        "can_create_person": conflict is None,
        "people": people,
        "companies": companies,
    }


def _person_phone_numbers(person: Person) -> list[str]:
    return list(
        person.contact_methods.filter(
            method_type=ContactMethod.MethodType.PHONE
        ).values_list("normalized_value", flat=True)
    )


def _schedule_person_phone_rematch(person: Person) -> None:
    numbers = sorted(set(_person_phone_numbers(person)))
    if not numbers:
        return
    from apps.crm.tasks import rematch_phone_calls_task

    transaction.on_commit(lambda: rematch_phone_calls_task.delay(numbers))


def _create_person_link(
    *, company: Company, data: NewPersonData, raw_phone: str | None
) -> CompanyPersonLink:
    with transaction.atomic():
        Company.objects.select_for_update().only("id").get(pk=company.pk)
        person = Person.objects.create(
            name=data["name"].strip(),
            email=data.get("email"),
            is_active=True,
        )
        has_active_people = CompanyPersonLink.objects.filter(
            company=company, is_active=True
        ).exists()
        link = CompanyPersonLink.objects.create(
            company=company,
            person=person,
            position=data.get("position"),
            notes=data.get("notes"),
            is_primary=data.get("is_primary", False) or not has_active_people,
            is_active=True,
        )
        if raw_phone is not None:
            from apps.company.serializers import set_primary_phone

            set_primary_phone(person, raw_phone)
        return link


def create_person_for_company(
    *, company: Company, data: NewPersonData
) -> CompanyPersonLink:
    raw_phone = data.get("phone")
    if not raw_phone:
        return _create_person_link(company=company, data=data, raw_phone=None)

    ownership = classify_phone_ownership(company=company, raw_phone=raw_phone)
    if not ownership["can_create_person"]:
        raise PersonPhoneConflictError(ownership)

    try:
        return _create_person_link(company=company, data=data, raw_phone=raw_phone)
    except DjangoValidationError as exc:
        persist_app_error(exc)
        ownership = classify_phone_ownership(company=company, raw_phone=raw_phone)
        raise PersonPhoneConflictError(ownership) from exc


def put_company_link(
    *, person: Person, company: Company, data: CompanyLinkData
) -> CompanyPersonLink:
    with transaction.atomic():
        Company.objects.select_for_update().only("id").get(pk=company.pk)
        existing = (
            CompanyPersonLink.objects.select_for_update()
            .filter(person=person, company=company)
            .first()
        )
        other_active_exists = (
            CompanyPersonLink.objects.filter(company=company, is_active=True)
            .exclude(person=person)
            .exists()
        )
        is_primary = data["is_primary"] or not other_active_exists
        if existing is None:
            link = CompanyPersonLink.objects.create(
                person=person,
                company=company,
                position=data["position"],
                notes=data["notes"],
                is_primary=is_primary,
                is_active=True,
            )
        else:
            existing.position = data["position"]
            existing.notes = data["notes"]
            existing.is_primary = is_primary
            existing.is_active = True
            existing.save(
                update_fields=[
                    "position",
                    "notes",
                    "is_primary",
                    "is_active",
                    "updated_at",
                ]
            )
            link = existing
        if not person.is_active:
            person.is_active = True
            person.save(update_fields=["is_active", "updated_at"])
        _schedule_person_phone_rematch(person)
        return link


def archive_person(*, person: Person) -> None:
    """Retire a person everywhere: deactivate all active links, then archive."""
    with transaction.atomic():
        locked = Person.objects.select_for_update().get(pk=person.pk)
        CompanyPersonLink.objects.filter(person=locked, is_active=True).update(
            is_active=False, is_primary=False
        )
        if locked.is_active:
            locked.is_active = False
            locked.save(update_fields=["is_active", "updated_at"])
        _schedule_person_phone_rematch(locked)


def remove_company_link(*, person: Person, company: Company) -> None:
    with transaction.atomic():
        link = (
            CompanyPersonLink.objects.select_for_update()
            .filter(person=person, company=company, is_active=True)
            .first()
        )
        if link is None:
            raise ValueError("Active company link not found")
        projected_company_ids = set(
            person.company_links.filter(is_active=True)
            .exclude(company=company)
            .values_list("company_id", flat=True)
        )
        phones = person.contact_methods.filter(
            method_type=ContactMethod.MethodType.PHONE
        )
        for method in phones:
            conflict = ContactMethod.conflicting_company(
                method.normalized_value,
                projected_company_ids,
                exclude_id=method.id,
            )
            if conflict is not None:
                raise ValueError(
                    f"Removing this link would make {method.value} conflict with "
                    f"{conflict.owner_display_name()}"
                )
        link.is_active = False
        link.is_primary = False
        link.save(update_fields=["is_active", "is_primary", "updated_at"])
        if not projected_company_ids and person.is_active:
            # Removing the person's last active company link retires them.
            person.is_active = False
            person.save(update_fields=["is_active", "updated_at"])
        _schedule_person_phone_rematch(person)
