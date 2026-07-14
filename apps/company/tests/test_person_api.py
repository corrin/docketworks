from unittest.mock import patch

from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.testing import BaseAPITestCase


class PersonApiTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.test_staff.is_office_staff = True
        self.test_staff.save(update_fields=["is_office_staff"])
        self.client.force_authenticate(user=self.test_staff)
        self.company_a = Company.objects.create(
            name="Acme Engineering", xero_last_modified=timezone.now()
        )
        self.company_b = Company.objects.create(
            name="Beta Fabrication", xero_last_modified=timezone.now()
        )

    def _person(
        self, name: str = "Jane Smith", company: Company | None = None
    ) -> Person:
        person = Person.objects.create(name=name, email="jane@example.com")
        if company is not None:
            CompanyPersonLink.objects.create(company=company, person=person)
        return person

    def test_directory_search_returns_one_person_for_multiple_matching_links(
        self,
    ) -> None:
        """A join-based search must not duplicate a person who works at two companies."""
        person = self._person(company=self.company_a)
        CompanyPersonLink.objects.create(company=self.company_b, person=person)

        response = self.client.get("/api/people/", {"q": "Fabrication"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "Jane Smith")

    def test_directory_includes_person_without_company(self) -> None:
        """Existing unaffiliated people must remain discoverable so they can be repaired."""
        self._person(name="Unaffiliated Person")

        response = self.client.get("/api/people/", {"q": "Unaffiliated"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["companies"], [])

    def test_create_company_person_is_atomic_on_cross_company_phone_conflict(
        self,
    ) -> None:
        """A duplicate-phone rejection must not leave an orphan Person behind."""
        existing = self._person(company=self.company_a)
        ContactMethod.objects.create(
            person=existing,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 111 1111",
            is_primary=True,
        )
        people_before = Person.objects.count()

        response = self.client.post(
            f"/api/companies/{self.company_b.id}/people/",
            {"name": "Jane Duplicate", "phone": "0211111111"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["status"], "people")
        self.assertFalse(response.json()["can_create_person"])
        self.assertEqual(response.json()["people"][0]["person_name"], "Jane Smith")
        self.assertEqual(Person.objects.count(), people_before)

    def test_same_company_shared_phone_can_create_another_person(self) -> None:
        """Two employees may legitimately share their company's office phone."""
        existing = self._person(company=self.company_a)
        ContactMethod.objects.create(
            person=existing,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 0000",
        )

        lookup = self.client.post(
            f"/api/companies/{self.company_a.id}/people/phone-ownership/",
            {"phone": "095550000"},
            format="json",
        )
        created = self.client.post(
            f"/api/companies/{self.company_a.id}/people/",
            {"name": "John Smith", "phone": "095550000"},
            format="json",
        )

        self.assertEqual(lookup.status_code, 200)
        self.assertTrue(lookup.json()["can_create_person"])
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["person_name"], "John Smith")

    def test_phone_ownership_rejects_a_value_without_digits(self) -> None:
        response = self.client.post(
            f"/api/companies/{self.company_a.id}/people/phone-ownership/",
            {"phone": "not a phone"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["phone"],
            ["Phone number must contain at least one digit"],
        )

    def test_contact_method_patch_cannot_change_its_owner(self) -> None:
        person = self._person(company=self.company_a)
        other_person = self._person(name="Other Person", company=self.company_a)
        method = ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 222 3333",
        )

        response = self.client.patch(
            f"/api/people/{person.id}/contact-methods/{method.id}/",
            {
                "label": "Mobile",
                "person": str(other_person.id),
                "company": str(self.company_b.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        method.refresh_from_db()
        self.assertEqual(method.person_id, person.id)
        self.assertIsNone(method.company_id)
        self.assertEqual(method.label, "Mobile")

    def test_put_reactivates_existing_company_link_without_duplication(self) -> None:
        """Restoring employment must reuse the soft-deleted unique link row."""
        person = self._person()
        link = CompanyPersonLink.objects.create(
            company=self.company_a, person=person, is_active=False
        )

        response = self.client.put(
            f"/api/people/{person.id}/company-links/{self.company_a.id}/",
            {"position": "Manager", "notes": "Restored", "is_primary": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        link.refresh_from_db()
        self.assertTrue(link.is_active)
        self.assertTrue(link.is_primary)
        self.assertEqual(link.position, "Manager")
        self.assertEqual(
            CompanyPersonLink.objects.filter(
                company=self.company_a, person=person
            ).count(),
            1,
        )

    def test_removing_link_preserves_person_and_other_company(self) -> None:
        """Unlinking one employer must not delete the shared human identity."""
        person = self._person(company=self.company_a)
        other = CompanyPersonLink.objects.create(company=self.company_b, person=person)

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            response = self.client.delete(
                f"/api/people/{person.id}/company-links/{self.company_a.id}/"
            )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(Person.objects.filter(id=person.id).exists())
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_removing_link_is_blocked_when_phone_would_cross_companies(self) -> None:
        """Relationship edits must not create the duplicate-phone problem they manage."""
        person = self._person(company=self.company_a)
        CompanyPersonLink.objects.create(company=self.company_b, person=person)
        ContactMethod.objects.create(
            company=self.company_a,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 444 4444",
        )
        ContactMethod.objects.create(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 444 4444",
        )

        response = self.client.delete(
            f"/api/people/{person.id}/company-links/{self.company_a.id}/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            CompanyPersonLink.objects.get(
                person=person, company=self.company_a
            ).is_active
        )

    def test_identity_patch_does_not_change_company_relationship(self) -> None:
        """Editing canonical identity must not overwrite company-specific role data."""
        person = self._person(company=self.company_a)
        link = CompanyPersonLink.objects.get(person=person, company=self.company_a)
        link.position = "Estimator"
        link.save(update_fields=["position"])

        response = self.client.patch(
            f"/api/people/{person.id}/",
            {"name": "Jane Brown"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        link.refresh_from_db()
        self.assertEqual(link.position, "Estimator")

    def test_old_person_links_collection_is_removed(self) -> None:
        """A caller migration must not accidentally leave two person-link APIs active."""
        response = self.client.get("/api/companies/person-links/")

        self.assertEqual(response.status_code, 404)
