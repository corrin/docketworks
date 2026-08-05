"""API tests for the first-class People endpoints."""

from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.person_service import put_company_link, remove_company_link

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.company.tests.urls"),
]


@pytest.fixture
def company_a() -> Company:
    return Company.objects.create(name="Acme Engineering", xero_last_modified=timezone.now())


@pytest.fixture
def company_b() -> Company:
    return Company.objects.create(name="Beta Fabrication", xero_last_modified=timezone.now())


def _person(name: str = "Jane Smith", company: Company | None = None) -> Person:
    person = Person.objects.create(name=name, email="jane@example.com")
    if company is not None:
        CompanyPersonLink.objects.create(company=company, person=person)
    return person


class TestDirectory:
    def test_search_returns_one_person_for_multiple_matching_links(
        self, client: Client, company_a: Company, company_b: Company
    ) -> None:
        """A join-based search must not duplicate a person who works at two companies."""
        person = _person(company=company_a)
        CompanyPersonLink.objects.create(company=company_b, person=person)

        response = client.get("/api/people/", {"q": "Fabrication"})

        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["name"] == "Jane Smith"

    def test_directory_includes_person_without_company(self, client: Client) -> None:
        """Existing unaffiliated people must remain discoverable so they can be repaired."""
        _person(name="Unaffiliated Person")

        response = client.get("/api/people/", {"q": "Unaffiliated"})

        assert response.status_code == 200
        assert response.json()["results"][0]["companies"] == []

    def test_directory_excludes_archived_by_default(
        self, client: Client, company_a: Company
    ) -> None:
        person = _person(company=company_a)
        client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")

        response = client.get("/api/people/")
        ids = [row["id"] for row in response.json()["results"]]
        assert str(person.id) not in ids

    def test_directory_includes_archived_when_requested(
        self, client: Client, company_a: Company
    ) -> None:
        person = _person(company=company_a)
        client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")

        response = client.get("/api/people/", {"include_archived": "true"})
        rows = {row["id"]: row for row in response.json()["results"]}
        assert str(person.id) in rows
        assert rows[str(person.id)]["is_active"] is False

    def test_directory_search_finds_person_by_phone(
        self, client: Client, company_a: Company
    ) -> None:
        person = _person(company=company_a)
        ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 3333",
            is_primary=True,
        )

        response = client.get("/api/people/", {"q": "0212223333"})

        assert response.json()["count"] == 1
        assert response.json()["results"][0]["primary_phone"] == "021 222 3333"


class TestCompanyPeopleCreate:
    def test_create_company_person_is_atomic_on_cross_company_phone_conflict(
        self, client: Client, company_a: Company, company_b: Company
    ) -> None:
        """A duplicate-phone rejection must not leave an orphan Person behind."""
        existing = _person(company=company_a)
        ContactMethod.objects.create(
            person=existing,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 1111",
            is_primary=True,
        )
        people_before = Person.objects.count()

        response = client.post(
            f"/api/companies/{company_b.id}/people/",
            {"name": "Jane Duplicate", "phone": "0211111111"},
            content_type="application/json",
        )

        assert response.status_code == 409
        assert response.json()["status"] == "people"
        assert response.json()["can_create_person"] is False
        assert response.json()["people"][0]["person_name"] == "Jane Smith"
        assert Person.objects.count() == people_before

    def test_same_company_shared_phone_can_create_another_person(
        self, client: Client, company_a: Company
    ) -> None:
        """Two employees may legitimately share their company's office phone."""
        existing = _person(company=company_a)
        ContactMethod.objects.create(
            person=existing,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 0000",
        )

        lookup = client.post(
            f"/api/companies/{company_a.id}/people/phone-ownership/",
            {"phone": "095550000"},
            content_type="application/json",
        )
        created = client.post(
            f"/api/companies/{company_a.id}/people/",
            {"name": "John Smith", "phone": "095550000"},
            content_type="application/json",
        )

        assert lookup.status_code == 200
        assert lookup.json()["can_create_person"] is True
        assert created.status_code == 201
        assert created.json()["person_name"] == "John Smith"

    def test_first_person_becomes_primary_contact(self, client: Client, company_a: Company) -> None:
        response = client.post(
            f"/api/companies/{company_a.id}/people/",
            {"name": "First Person"},
            content_type="application/json",
        )

        assert response.status_code == 201
        assert response.json()["is_primary"] is True

    def test_phone_ownership_rejects_a_value_without_digits(
        self, client: Client, company_a: Company
    ) -> None:
        response = client.post(
            f"/api/companies/{company_a.id}/people/phone-ownership/",
            {"phone": "not a phone"},
            content_type="application/json",
        )

        # Ninja returns its native 422 field-error shape.
        # for request validation (recorded drift, apps/core/envelope.py).
        assert response.status_code == 422

    def test_phone_ownership_offers_restore_for_an_archived_person(
        self, client: Client, company_a: Company
    ) -> None:
        """An archived person who still owns a phone must come back as status
        'people' (not 'company') so the modal can offer to restore the link."""
        person = _person(company=company_a)
        ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 2222",
            is_primary=True,
        )
        client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")
        person.refresh_from_db()
        assert person.is_active is False

        response = client.post(
            f"/api/companies/{company_a.id}/people/phone-ownership/",
            {"phone": "0212222222"},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "people"
        assert body["people"][0]["person_id"] == str(person.id)
        company_links = body["people"][0]["company_links"]
        link = next(link for link in company_links if link["company_id"] == str(company_a.id))
        assert link["is_active"] is False


class TestContactMethods:
    def test_contact_method_patch_cannot_change_its_owner(
        self, client: Client, company_a: Company, company_b: Company
    ) -> None:
        person = _person(company=company_a)
        other_person = _person(name="Other Person", company=company_a)
        method = ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 3333",
        )

        response = client.patch(
            f"/api/people/{person.id}/contact-methods/{method.id}/",
            {
                "label": "Mobile",
                "person": str(other_person.id),
                "company": str(company_b.id),
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        method.refresh_from_db()
        assert method.person_id == person.id
        assert method.company_id is None
        assert method.label == "Mobile"

    def test_contact_methods_are_reachable_for_an_archived_person(
        self, client: Client, company_a: Company
    ) -> None:
        """The PersonDetail page loads contact-methods alongside the person; a 404
        here fails the whole Promise.all and hides the restore-link button."""
        person = _person(company=company_a)
        client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")
        person.refresh_from_db()
        assert person.is_active is False

        response = client.get(f"/api/people/{person.id}/contact-methods/")

        assert response.status_code == 200

    def test_archived_company_link_does_not_leak_company_name(
        self, client: Client, company_a: Company
    ) -> None:
        """An inactive link's company must not leak into company_name — the
        field stays consistent with owner_company (both empty)."""
        person = _person(company=company_a)
        method = ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 777 8888",
        )
        archived = client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")
        assert archived.status_code == 204

        response = client.get(f"/api/people/{person.id}/contact-methods/")

        assert response.status_code == 200
        rows = response.json()
        assert [row["id"] for row in rows] == [str(method.id)]
        assert rows[0]["owner_company"] == ""
        assert rows[0]["company_name"] == ""

    def test_changing_phone_to_email_rematches_the_old_phone(
        self,
        client: Client,
        company_a: Company,
        django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    ) -> None:
        """Changing method type must clear calls matched to the former phone."""
        person = _person(company=company_a)
        method = ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 3333",
        )

        with (
            patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.patch(
                f"/api/people/{person.id}/contact-methods/{method.id}/",
                {
                    "method_type": ContactMethod.MethodType.EMAIL,
                    "value": "jane@example.com",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        rematch.assert_called_once_with(["+64212223333"])

    def test_create_and_delete_person_contact_method(
        self, client: Client, company_a: Company
    ) -> None:
        person = _person(company=company_a)

        created = client.post(
            f"/api/people/{person.id}/contact-methods/",
            {"method_type": "phone", "value": "021 999 8888", "is_primary": True},
            content_type="application/json",
        )
        assert created.status_code == 201
        body = created.json()
        assert body["normalized_value"] == "+64219998888"
        assert body["person_name"] == person.name
        assert body["owner_company"] == str(company_a.id)

        deleted = client.delete(f"/api/people/{person.id}/contact-methods/{body['id']}/")
        assert deleted.status_code == 204
        assert person.contact_methods.count() == 0


class TestCompanyLinks:
    def test_put_reactivates_existing_company_link_without_duplication(
        self, client: Client, company_a: Company
    ) -> None:
        """Restoring employment must reuse the soft-deleted unique link row."""
        person = _person()
        link = CompanyPersonLink.objects.create(company=company_a, person=person, is_active=False)

        response = client.put(
            f"/api/people/{person.id}/company-links/{company_a.id}/",
            {"position": "Manager", "notes": "Restored", "is_primary": False},
            content_type="application/json",
        )

        assert response.status_code == 200
        link.refresh_from_db()
        assert link.is_active
        assert link.is_primary
        assert link.position == "Manager"
        assert CompanyPersonLink.objects.filter(company=company_a, person=person).count() == 1

    def test_removing_link_preserves_person_and_other_company(
        self, client: Client, company_a: Company, company_b: Company
    ) -> None:
        """Unlinking one employer must not delete the shared human identity."""
        person = _person(company=company_a)
        other = CompanyPersonLink.objects.create(company=company_b, person=person)

        response = client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")

        assert response.status_code == 204
        assert Person.objects.filter(id=person.id).exists()
        person.refresh_from_db()
        assert person.is_active
        other.refresh_from_db()
        assert other.is_active

    def test_removing_last_link_archives_person(self, client: Client, company_a: Company) -> None:
        """Removing a person's only active company link retires (archives) them."""
        person = _person(company=company_a)

        response = client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")

        assert response.status_code == 204
        person.refresh_from_db()
        assert person.is_active is False
        link = CompanyPersonLink.objects.get(person=person, company=company_a)
        assert link.is_active is False

    def test_restoring_a_link_unarchives_the_person(self, company_a: Company) -> None:
        """Adding/reactivating any company link brings an archived person back."""
        person = _person(company=company_a)
        remove_company_link(person=person, company=company_a)
        person.refresh_from_db()
        assert person.is_active is False

        put_company_link(
            person=person,
            company=company_a,
            data={"position": None, "notes": None, "is_primary": False},
        )
        person.refresh_from_db()
        assert person.is_active

    def test_restore_link_over_http_unarchives_archived_person(
        self, client: Client, company_a: Company
    ) -> None:
        person = _person(company=company_a)
        client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")
        person.refresh_from_db()
        assert person.is_active is False

        response = client.put(
            f"/api/people/{person.id}/company-links/{company_a.id}/",
            {"position": None, "notes": None, "is_primary": False},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is True
        person.refresh_from_db()
        assert person.is_active

    def test_removing_link_is_blocked_when_phone_would_cross_companies(
        self, client: Client, company_a: Company, company_b: Company
    ) -> None:
        """Relationship edits must not create the duplicate-phone problem they manage."""
        person = _person(company=company_a)
        CompanyPersonLink.objects.create(company=company_b, person=person)
        ContactMethod.objects.create(
            company=company_a,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 444 4444",
        )
        ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 444 4444",
        )

        response = client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")

        assert response.status_code == 400
        assert CompanyPersonLink.objects.get(person=person, company=company_a).is_active


class TestIdentity:
    def test_identity_patch_does_not_change_company_relationship(
        self, client: Client, company_a: Company
    ) -> None:
        """Editing canonical identity must not overwrite company-specific role data."""
        person = _person(company=company_a)
        link = CompanyPersonLink.objects.get(person=person, company=company_a)
        link.position = "Estimator"
        link.save(update_fields=["position"])

        response = client.patch(
            f"/api/people/{person.id}/",
            {"name": "Jane Brown"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Jane Brown"
        link.refresh_from_db()
        assert link.position == "Estimator"

    def test_detail_returns_an_archived_person(self, client: Client, company_a: Company) -> None:
        person = _person(company=company_a)
        client.delete(f"/api/people/{person.id}/company-links/{company_a.id}/")

        response = client.get(f"/api/people/{person.id}/")
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_archive_person_endpoint_deactivates_links_and_archives(
        self, client: Client, company_a: Company, company_b: Company
    ) -> None:
        person = _person(company=company_a)
        CompanyPersonLink.objects.create(company=company_b, person=person)

        response = client.post(f"/api/people/{person.id}/archive/")

        assert response.status_code == 200
        assert response.json()["is_active"] is False
        person.refresh_from_db()
        assert person.is_active is False
        assert not CompanyPersonLink.objects.filter(person=person, is_active=True).exists()

    def test_old_person_links_collection_is_removed(self, client: Client) -> None:
        """A caller migration must not accidentally leave two person-link APIs active."""
        response = client.get("/api/companies/person-links/")
        assert response.status_code == 404
