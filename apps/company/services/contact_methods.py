"""Primary-phone upsert/clear logic shared by company and person surfaces.

Ported from v1 ``apps/company/serializers.set_primary_phone`` and
``CompanyRestService._clear_company_primary_phone`` — hoisted out of the
serializer module because it is business logic, not wire-shaping (ADR 0039:
one implementation, one obvious home).
"""

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch, QuerySet

from apps.company.models import (
    PRIMARY_PHONE_ORDERING,
    Company,
    CompanyPersonLink,
    ContactMethod,
    Person,
)

logger = logging.getLogger(__name__)


def schedule_phone_rematch(numbers: Iterable[str]) -> None:
    """Schedule the CRM call-rematch for changed phone numbers, post-commit.

    The single seam for the side effect v1 triggered from five call sites
    (serializer, viewset, person views/service, company service):
    ``rematch_phone_calls_task.delay(numbers)`` re-links PhoneCallRecord rows
    to the number's new owner. Always via ``transaction.on_commit`` so the
    worker never races uncommitted data (v1's viewset called ``.delay``
    directly; the on_commit form is the one canonical behaviour here).
    """
    sorted_numbers = sorted(set(numbers))
    if not sorted_numbers:
        return
    # Function-level import: company <-> crm cycle (v1 did the same).
    from apps.crm.tasks import rematch_phone_calls_task  # noqa: PLC0415

    transaction.on_commit(lambda: rematch_phone_calls_task.delay(sorted_numbers))


def set_primary_phone(owner: Company | Person, raw_value: str) -> None:
    """Point the owner's primary phone at ``raw_value`` (non-blank).

    Reuses an existing method carrying the same normalized number (promoting
    it) or the current primary (renumbering it) before creating a new row, so
    the per-owner uniqueness and single-primary constraints hold. Ownership
    conflicts raise the model's ValidationError for the caller to surface.
    """
    value = raw_value.strip()
    owner_field = "company" if isinstance(owner, Company) else "person"
    phone_methods = ContactMethod.objects.filter(
        method_type=ContactMethod.MethodType.PHONE, **{owner_field: owner}
    )
    old_primary = phone_methods.filter(is_primary=True).first()
    old_number = old_primary.normalized_value if old_primary else ""
    normalized_value = ContactMethod.normalize_phone(value)
    if not normalized_value:
        raise DjangoValidationError("Phone number must contain at least one digit")

    same_number = phone_methods.filter(normalized_value=normalized_value).first()

    if same_number is not None:
        same_number.value = value
        same_number.is_primary = True  # save() demotes any other primary
        same_number.save()
        method = same_number
    elif old_primary is not None:
        old_primary.value = value
        old_primary.save()
        method = old_primary
    else:
        method = ContactMethod.objects.create(
            method_type=ContactMethod.MethodType.PHONE,
            value=value,
            is_primary=True,
            **{owner_field: owner},
        )

    schedule_phone_rematch(number for number in {old_number, method.normalized_value} if number)


def clear_company_primary_phone(company: Company) -> None:
    """Delete the company's primary phone method (blank phone on update)."""
    primary = (
        ContactMethod.objects.filter(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            is_primary=True,
        )
        .order_by(*PRIMARY_PHONE_ORDERING)
        .first()
    )
    if primary is None:
        logger.info(
            "Company primary phone clear requested but no primary phone exists",
            extra={
                "company_id": str(company.id),
                "operation": "company_phone_clear_noop",
            },
        )
        return

    old_number = primary.normalized_value
    primary.delete()
    if not old_number:
        logger.warning(
            "Deleted company primary phone without normalized value",
            extra={
                "company_id": str(company.id),
                "contact_method_id": str(primary.id),
                "operation": "company_phone_clear_missing_normalized_value",
            },
        )
        return

    schedule_phone_rematch([old_number])


def phone_number_for_rematch(method: ContactMethod) -> str | None:
    """Return the normalized number a CRM rematch should run for (None for emails)."""
    if method.method_type != ContactMethod.MethodType.PHONE:
        return None
    if method.normalized_value:
        return method.normalized_value
    return ContactMethod.normalize_phone(method.value) or None


# ── Wire formatting + CRUD (v1 ContactMethodSerializer / ContactMethodViewSet) ──


class ContactMethodData(TypedDict):
    """v1 ContactMethodSerializer response row."""

    id: UUID
    company: UUID | None
    owner_company: str
    company_name: str
    person: UUID | None
    person_name: str
    method_type: str
    value: str
    normalized_value: str
    label: str | None
    is_primary: bool
    source: str
    created_at: datetime
    updated_at: datetime


class ContactMethodWriteData(TypedDict, total=False):
    """Validated contact-method write payload (v1 ContactMethodRequest fields)."""

    company: UUID | None
    person: UUID | None
    method_type: str
    value: str
    label: str | None
    is_primary: bool
    source: str


def _ordered_company_links(person: Person) -> list[CompanyPersonLink]:
    prefetched_links = getattr(person, "_prefetched_objects_cache", {}).get("company_links")
    if prefetched_links is not None:
        return sorted(
            prefetched_links,
            key=lambda link: (not link.is_primary, link.company.name),
        )
    # Match the prefetched branch's contract (contact_method_queryset prefetches
    # active links only) — without the filter, an archived link's company name
    # leaks into company_name while owner_company correctly reads "".
    return list(
        person.company_links.filter(is_active=True)
        .select_related("company")
        .order_by("-is_primary", "company__name")
    )


def contact_method_data(method: ContactMethod) -> ContactMethodData:
    """Build the v1 ContactMethodSerializer wire row for one method."""
    owner_company = ""
    company_name = ""
    if method.company_id:
        owner_company = str(method.company_id)
        company_name = method.company.name if method.company else ""
    elif method.person_id:
        company_id = method.owner_company_id()
        owner_company = str(company_id) if company_id else ""
        person = method.person
        if person is None:
            raise RuntimeError(f"Contact method {method.id} has no person")
        link = next(iter(_ordered_company_links(person)), None)
        company_name = link.company.name if link else ""
    return {
        "id": method.id,
        "company": method.company_id,
        "owner_company": owner_company,
        "company_name": company_name,
        "person": method.person_id,
        "person_name": method.person.name if method.person else "",
        "method_type": method.method_type,
        "value": method.value,
        "normalized_value": method.normalized_value,
        "label": method.label,
        "is_primary": method.is_primary,
        "source": method.source,
        "created_at": method.created_at,
        "updated_at": method.updated_at,
    }


def contact_method_queryset() -> QuerySet[ContactMethod]:
    """Return the base queryset with the joins the wire formatter needs."""
    return ContactMethod.objects.select_related("company", "person").prefetch_related(
        Prefetch(
            "person__company_links",
            queryset=CompanyPersonLink.objects.filter(is_active=True).select_related("company"),
        ),
    )


def _resolve_owner(
    data: ContactMethodWriteData, instance: ContactMethod | None
) -> tuple[Company | None, Person | None]:
    """Resolve the proposed owner pair, falling back to the instance on partial writes.

    Raises:
        DjangoValidationError: unknown company/person id, or not exactly one owner.
    """
    if "company" in data:
        company_id = data["company"]
        company = None
        if company_id is not None:
            company = Company.objects.filter(id=company_id).first()
            if company is None:
                raise DjangoValidationError(f"Company {company_id} does not exist")
    else:
        company = instance.company if instance is not None else None

    if "person" in data:
        person_id = data["person"]
        person = None
        if person_id is not None:
            person = Person.objects.filter(id=person_id).first()
            if person is None:
                raise DjangoValidationError(f"Person {person_id} does not exist")
    else:
        person = instance.person if instance is not None else None

    owner_count = sum(1 for owner in (company, person) if owner)
    if owner_count != 1:
        raise DjangoValidationError("Exactly one of company or person is required")
    return company, person


def save_contact_method(
    data: ContactMethodWriteData, *, instance: ContactMethod | None = None
) -> ContactMethod:
    """Create or update a contact method (v1 ContactMethodSerializer semantics).

    The one-number-one-company phone guard, normalization, and
    primary-demotion all live on ``ContactMethod.save()`` (ADR 0039 — model
    behaviour is not duplicated here). Schedules the CRM phone rematch for
    the numbers involved.

    Raises:
        DjangoValidationError: owner problems or phone-ownership conflicts.
        ValueError: blank value (from the model).
    """
    company, person = _resolve_owner(data, instance)
    method = instance if instance is not None else ContactMethod()
    old_number = phone_number_for_rematch(method) if instance is not None else None
    method.company = company
    method.person = person
    if "method_type" in data:
        method.method_type = data["method_type"]
    if "value" in data:
        method.value = data["value"]
    if "label" in data:
        method.label = data["label"]
    if "is_primary" in data:
        method.is_primary = data["is_primary"]
    if "source" in data:
        method.source = data["source"]
    method.save()
    new_number = phone_number_for_rematch(method)
    schedule_phone_rematch(number for number in (old_number, new_number) if number)
    return method


def delete_contact_method(method: ContactMethod) -> None:
    """Delete a contact method and schedule the CRM rematch for its number."""
    number = phone_number_for_rematch(method)
    method.delete()
    if number:
        schedule_phone_rematch([number])
