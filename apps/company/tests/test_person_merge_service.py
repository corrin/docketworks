"""Tests for apps.company.services.person_merge_service (ported from v1).

Merging must preserve references (including Jobs pointing at the person)
while retaining uniqueness invariants.
"""

from unittest.mock import patch

import pytest

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.person_merge_service import merge_people
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job, make_phone_call
from apps.core.models import AppError

pytestmark = pytest.mark.django_db


def test_moves_cross_company_relationships_and_references(office_staff: Staff) -> None:
    source = Person.objects.create(name="J Smith", email="old@example.com")
    destination = Person.objects.create(name="Jane Smith", email="canonical@example.com")
    source_company = make_company("Source Co")
    destination_company = make_company("Destination Co")
    CompanyPersonLink.objects.create(company=source_company, person=source)
    CompanyPersonLink.objects.create(company=destination_company, person=destination)
    method = ContactMethod.objects.create(
        person=source,
        method_type=ContactMethod.MethodType.PHONE,
        value="021 555 123",
    )
    call = make_phone_call(person=source)
    job = make_job(source_company, office_staff, name="Merge Person Job")
    job.person = source
    job.save(staff=office_staff, update_fields=["person"])

    counts = merge_people(source.id, destination.id, office_staff)

    destination.refresh_from_db()
    method.refresh_from_db()
    call.refresh_from_db()
    job.refresh_from_db()
    assert not Person.objects.filter(id=source.id).exists()
    assert destination.name == "Jane Smith"
    assert destination.email == "canonical@example.com"
    assert destination.company_links.count() == 2
    assert method.person_id == destination.id
    assert call.person_id == destination.id
    assert job.person_id == destination.id
    assert counts["links_moved"] == 1
    assert counts["jobs"] == 1
    assert counts["phone_calls"] == 1


def test_collapses_same_company_link_and_exact_method(office_staff: Staff) -> None:
    source = Person.objects.create(name="J Smith")
    destination = Person.objects.create(name="Jane Smith")
    company: Company = make_company("Acme")
    source_link = CompanyPersonLink.objects.create(
        company=company,
        person=source,
        position="Foreman",
        notes="Source notes",
        is_primary=True,
    )
    destination_link = CompanyPersonLink.objects.create(company=company, person=destination)
    source_method = ContactMethod.objects.create(
        person=source,
        method_type=ContactMethod.MethodType.PHONE,
        value="021 555 123",
        label="Mobile",
        is_primary=True,
    )
    destination_method = ContactMethod.objects.create(
        person=destination,
        method_type=ContactMethod.MethodType.PHONE,
        value="+64 21 555 123",
    )

    counts = merge_people(source.id, destination.id, office_staff)

    destination_link.refresh_from_db()
    destination_method.refresh_from_db()
    assert not CompanyPersonLink.objects.filter(id=source_link.id).exists()
    assert destination.company_links.count() == 1
    assert destination_link.position == "Foreman"
    assert destination_link.notes == "Source notes"
    assert destination_link.is_primary
    assert not ContactMethod.objects.filter(id=source_method.id).exists()
    assert destination.contact_methods.count() == 1
    assert destination_method.label == "Mobile"
    assert destination_method.is_primary
    assert counts["links_collapsed"] == 1
    assert counts["contact_methods_collapsed"] == 1


def test_preserves_source_scalar_fields_missing_from_destination(
    office_staff: Staff,
) -> None:
    source = Person.objects.create(name="Jane Smith", email="jane@example.com", is_active=True)
    destination = Person.objects.create(name="J Smith", is_active=False)

    merge_people(source.id, destination.id, office_staff)

    destination.refresh_from_db()
    assert destination.email == "jane@example.com"
    assert destination.is_active


def test_unexpected_failure_rolls_back_and_persists_once(office_staff: Staff) -> None:
    """A mid-merge failure must not strand links or create duplicate AppErrors."""
    source = Person.objects.create(name="J Smith")
    destination = Person.objects.create(name="Jane Smith")
    source_link = CompanyPersonLink.objects.create(company=make_company("Acme"), person=source)
    before_errors = AppError.objects.count()

    with (
        patch(
            "apps.company.services.person_merge_service._merge_contact_methods",
            side_effect=RuntimeError("merge failed"),
        ),
        pytest.raises(RuntimeError),
    ):
        merge_people(source.id, destination.id, office_staff)

    source_link.refresh_from_db()
    assert source_link.person_id == source.id
    assert Person.objects.filter(id=source.id).exists()
    assert AppError.objects.count() == before_errors + 1
