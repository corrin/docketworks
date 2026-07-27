import uuid
from unittest.mock import patch

from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.person_merge_service import merge_people
from apps.crm.models import PhoneCallRecord
from apps.job.models import Job
from apps.testing import BaseTestCase
from apps.workflow.models import AppError


class PersonMergeServiceTests(BaseTestCase):
    """Merging must preserve references while retaining uniqueness invariants."""

    def _company(self, name: str) -> Company:
        return Company.objects.create(name=name, xero_last_modified=timezone.now())

    def _call(self, person: Person) -> PhoneCallRecord:
        now = timezone.now()
        return PhoneCallRecord.objects.create(
            provider_call_id=f"person-merge:{uuid.uuid4()}",
            account_code="account",
            call_datetime=now,
            call_date=timezone.localdate(),
            call_time=now.time(),
            person=person,
            raw_json={},
        )

    def _job(self, person: Person, company: Company) -> Job:
        job = Job(
            name="Merge Person Job",
            job_number=998001,
            company=company,
            person=person,
        )
        job.save(staff=self.test_staff)
        return job

    def test_moves_cross_company_relationships_and_references(self) -> None:
        source = Person.objects.create(name="J Smith", email="old@example.com")
        destination = Person.objects.create(
            name="Jane Smith", email="canonical@example.com"
        )
        source_company = self._company("Source Co")
        destination_company = self._company("Destination Co")
        CompanyPersonLink.objects.create(company=source_company, person=source)
        CompanyPersonLink.objects.create(
            company=destination_company, person=destination
        )
        method = ContactMethod.objects.create(
            person=source,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        job = self._job(source, source_company)
        call = self._call(source)

        counts = merge_people(source.id, destination.id, self.test_staff)

        destination.refresh_from_db()
        method.refresh_from_db()
        job.refresh_from_db()
        call.refresh_from_db()
        self.assertFalse(Person.objects.filter(id=source.id).exists())
        self.assertEqual(destination.name, "Jane Smith")
        self.assertEqual(destination.email, "canonical@example.com")
        self.assertEqual(destination.company_links.count(), 2)
        self.assertEqual(method.person_id, destination.id)
        self.assertEqual(job.person_id, destination.id)
        self.assertEqual(call.person_id, destination.id)
        self.assertEqual(counts["links_moved"], 1)
        self.assertEqual(counts["jobs"], 1)
        self.assertEqual(counts["phone_calls"], 1)

    def test_collapses_same_company_link_and_exact_method(self) -> None:
        source = Person.objects.create(name="J Smith")
        destination = Person.objects.create(name="Jane Smith")
        company = self._company("Acme")
        source_link = CompanyPersonLink.objects.create(
            company=company,
            person=source,
            position="Foreman",
            notes="Source notes",
            is_primary=True,
        )
        destination_link = CompanyPersonLink.objects.create(
            company=company,
            person=destination,
        )
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

        counts = merge_people(source.id, destination.id, self.test_staff)

        destination_link.refresh_from_db()
        destination_method.refresh_from_db()
        self.assertFalse(CompanyPersonLink.objects.filter(id=source_link.id).exists())
        self.assertEqual(destination.company_links.count(), 1)
        self.assertEqual(destination_link.position, "Foreman")
        self.assertEqual(destination_link.notes, "Source notes")
        self.assertTrue(destination_link.is_primary)
        self.assertFalse(ContactMethod.objects.filter(id=source_method.id).exists())
        self.assertEqual(destination.contact_methods.count(), 1)
        self.assertEqual(destination_method.label, "Mobile")
        self.assertTrue(destination_method.is_primary)
        self.assertEqual(counts["links_collapsed"], 1)
        self.assertEqual(counts["contact_methods_collapsed"], 1)

    def test_preserves_source_scalar_fields_missing_from_destination(self) -> None:
        source = Person.objects.create(
            name="Jane Smith",
            email="jane@example.com",
            is_active=True,
        )
        destination = Person.objects.create(name="J Smith", is_active=False)

        merge_people(source.id, destination.id, self.test_staff)

        destination.refresh_from_db()
        self.assertEqual(destination.email, "jane@example.com")
        self.assertTrue(destination.is_active)

    def test_unexpected_failure_rolls_back_and_persists_once(self) -> None:
        """A mid-merge failure must not strand links or create duplicate AppErrors."""
        source = Person.objects.create(name="J Smith")
        destination = Person.objects.create(name="Jane Smith")
        source_link = CompanyPersonLink.objects.create(
            company=self._company("Acme"), person=source
        )
        before_errors = AppError.objects.count()

        with patch(
            "apps.company.services.person_merge_service._merge_contact_methods",
            side_effect=RuntimeError("merge failed"),
        ):
            with self.assertRaises(RuntimeError):
                merge_people(source.id, destination.id, self.test_staff)

        source_link.refresh_from_db()
        self.assertEqual(source_link.person_id, source.id)
        self.assertTrue(Person.objects.filter(id=source.id).exists())
        self.assertEqual(AppError.objects.count(), before_errors + 1)
