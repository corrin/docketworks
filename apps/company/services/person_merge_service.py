"""Atomic reassignment of one duplicate Person into a canonical Person."""

from typing import TypedDict
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import CompanyPersonLink, ContactMethod, Person
from apps.workflow.services.error_persistence import persist_app_error


class PersonMergeCounts(TypedDict):
    jobs: int
    phone_calls: int
    links_moved: int
    links_collapsed: int
    contact_methods_moved: int
    contact_methods_collapsed: int


def _merge_links(source: Person, destination: Person) -> tuple[int, int]:
    destination_links = {
        link.company_id: link
        for link in CompanyPersonLink.objects.filter(person=destination)
    }
    moved = 0
    collapsed = 0
    for source_link in CompanyPersonLink.objects.filter(person=source).order_by("id"):
        destination_link = destination_links.get(source_link.company_id)
        if destination_link is None:
            source_link.person = destination
            source_link.save(update_fields=["person", "updated_at"])
            destination_links[source_link.company_id] = source_link
            moved += 1
            continue

        update_fields = ["updated_at"]
        if not destination_link.position and source_link.position:
            destination_link.position = source_link.position
            update_fields.append("position")
        if not destination_link.notes and source_link.notes:
            destination_link.notes = source_link.notes
            update_fields.append("notes")
        if source_link.is_active and not destination_link.is_active:
            destination_link.is_active = True
            update_fields.append("is_active")
        if source_link.is_primary and not destination_link.is_primary:
            destination_link.is_primary = True
            update_fields.append("is_primary")
        destination_link.save(update_fields=update_fields)
        source_link.delete()
        collapsed += 1
    return moved, collapsed


def _merge_contact_methods(source: Person, destination: Person) -> tuple[int, int]:
    destination_methods = {
        (method.method_type, method.normalized_value): method
        for method in ContactMethod.objects.filter(person=destination)
    }
    destination_primary_types = set(
        ContactMethod.objects.filter(person=destination, is_primary=True).values_list(
            "method_type", flat=True
        )
    )
    moved = 0
    collapsed = 0
    now = timezone.now()
    for source_method in ContactMethod.objects.filter(person=source).order_by("id"):
        key = (source_method.method_type, source_method.normalized_value)
        destination_method = destination_methods.get(key)
        if destination_method is not None:
            update_fields = ["updated_at"]
            if not destination_method.label and source_method.label:
                destination_method.label = source_method.label
                update_fields.append("label")
            if (
                source_method.is_primary
                and source_method.method_type not in destination_primary_types
            ):
                destination_method.is_primary = True
                destination_primary_types.add(source_method.method_type)
                update_fields.append("is_primary")
            destination_method.save(update_fields=update_fields)
            source_method.delete()
            collapsed += 1
            continue

        moving_primary = source_method.is_primary
        if source_method.method_type in destination_primary_types:
            moving_primary = False
        elif moving_primary:
            destination_primary_types.add(source_method.method_type)

        # The ownership change is the repair itself. Bypass save()'s assignment
        # guard so grandfathered phone data cannot prevent its documented remedy.
        ContactMethod.objects.filter(pk=source_method.pk).update(
            person=destination,
            is_primary=moving_primary,
            updated_at=now,
        )
        destination_methods[key] = source_method
        moved += 1
    return moved, collapsed


def merge_people(
    source_id: UUID,
    destination_id: UUID,
    staff: Staff,
) -> PersonMergeCounts:
    """Merge ``source_id`` into ``destination_id`` and delete the source row."""
    if source_id == destination_id:
        raise ValueError("Source and destination Person must be different")

    from apps.crm.models import PhoneCallRecord
    from apps.job.models import Job

    try:
        with transaction.atomic():
            people = {
                person.id: person
                for person in Person.objects.select_for_update()
                .filter(id__in=[source_id, destination_id])
                .order_by("id")
            }
            source = people.get(source_id)
            if source is None:
                raise ValueError(f"Source Person {source_id} does not exist")
            destination = people.get(destination_id)
            if destination is None:
                raise ValueError(f"Destination Person {destination_id} does not exist")

            update_fields = ["updated_at"]
            if not destination.email and source.email:
                destination.email = source.email
                update_fields.append("email")
            if source.is_active and not destination.is_active:
                destination.is_active = True
                update_fields.append("is_active")
            destination.save(update_fields=update_fields)

            links_moved, links_collapsed = _merge_links(source, destination)
            methods_moved, methods_collapsed = _merge_contact_methods(
                source, destination
            )

            jobs_moved = 0
            for job in Job.objects.filter(person=source).order_by("id"):
                job.person = destination
                job.save(staff=staff, update_fields=["person"])
                jobs_moved += 1

            calls_moved = PhoneCallRecord.objects.filter(person=source).update(
                person=destination
            )
            source.delete()
            return {
                "jobs": jobs_moved,
                "phone_calls": calls_moved,
                "links_moved": links_moved,
                "links_collapsed": links_collapsed,
                "contact_methods_moved": methods_moved,
                "contact_methods_collapsed": methods_collapsed,
            }
    except ValueError:
        raise
    except Exception as exc:
        persist_app_error(exc)
        raise
