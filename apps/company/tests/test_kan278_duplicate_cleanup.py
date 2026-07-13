from unittest.mock import patch

from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services import kan278_duplicate_cleanup
from apps.company.services.kan278_duplicate_cleanup import (
    apply_reviewed_duplicate_cleanup,
)
from apps.job.models import Job
from apps.testing import BaseTestCase


class ReviewedDuplicateCleanupTests(BaseTestCase):
    def test_applies_company_first_then_person_merge(self) -> None:
        destination_company = Company.objects.create(
            name="Northland Roofs NZ",
            xero_last_modified=timezone.now(),
        )
        source_company = Company.objects.create(
            name="CASH SALE - Northland Roofs NZ",
            xero_contact_id="source-xero-id",
            xero_last_modified=timezone.now(),
        )
        destination_person = Person.objects.create(
            name="ACE PUNIA", email="ace@example.com"
        )
        source_person = Person.objects.create(name="Ace Punia", email="ACE@example.com")
        destination_link = CompanyPersonLink.objects.create(
            company=destination_company,
            person=destination_person,
        )
        source_link = CompanyPersonLink.objects.create(
            company=source_company,
            person=source_person,
        )
        ContactMethod.objects.create(
            person=source_person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        job = Job(
            company=source_company,
            person=source_person,
            name="Northland test",
            job_number=998278,
        )
        job.save(staff=self.test_staff)

        with (
            patch.object(
                kan278_duplicate_cleanup,
                "REVIEWED_COMPANY_MERGES",
                ((str(source_company.id), str(destination_company.id)),),
            ),
            patch.object(
                kan278_duplicate_cleanup,
                "REVIEWED_PERSON_LINK_EDGES",
                ((str(source_link.id), str(destination_link.id)),),
            ),
            patch.object(
                kan278_duplicate_cleanup,
                "MATT_GREEN_LINK_ID",
                source_link.id,
            ),
            patch.object(
                kan278_duplicate_cleanup,
                "MATT_WRONG_METHOD_VALUES",
                set(),
            ),
        ):
            company_count, person_count = apply_reviewed_duplicate_cleanup()

        source_company.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(company_count, 1)
        self.assertEqual(person_count, 1)
        self.assertEqual(source_company.merged_into_id, destination_company.id)
        self.assertFalse(source_company.allow_jobs)
        self.assertEqual(source_company.xero_contact_id, "source-xero-id")
        self.assertEqual(job.company_id, destination_company.id)
        self.assertIn(job.person_id, {source_person.id, destination_person.id})
        self.assertEqual(
            Person.objects.filter(
                id__in=[source_person.id, destination_person.id]
            ).count(),
            1,
        )
        self.assertEqual(
            CompanyPersonLink.objects.filter(company=destination_company).count(), 1
        )

    def test_rejects_partially_present_company_evidence(self) -> None:
        destination = Company.objects.create(
            name="Destination",
            xero_last_modified=timezone.now(),
        )

        with patch.object(
            kan278_duplicate_cleanup,
            "REVIEWED_COMPANY_MERGES",
            (("00000000-0000-0000-0000-000000000278", str(destination.id)),),
        ):
            with self.assertRaisesRegex(RuntimeError, "Company merge evidence"):
                apply_reviewed_duplicate_cleanup()
