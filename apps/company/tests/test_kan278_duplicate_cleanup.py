import re
from pathlib import Path
from unittest.mock import patch

from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services import kan278_duplicate_cleanup
from apps.company.services.kan278_duplicate_cleanup import (
    CompanyMergeDecision,
    PersonMergeDecision,
    PersonSelector,
    apply_reviewed_duplicate_cleanup,
)
from apps.job.models import Job
from apps.testing import BaseTestCase


class ReviewedDuplicateCleanupTests(BaseTestCase):
    def test_flattens_existing_multi_hop_company_merges(self) -> None:
        terminal = Company.objects.create(
            name="Terminal Company",
            xero_last_modified=timezone.now(),
        )
        middle = Company.objects.create(
            name="Middle Company",
            xero_last_modified=timezone.now(),
            merged_into=terminal,
        )
        source = Company.objects.create(
            name="Source Company",
            xero_last_modified=timezone.now(),
            merged_into=middle,
        )
        job = Job(
            company=source,
            name="Stranded historical job",
            job_number=998279,
        )
        job.save(staff=self.test_staff)

        kan278_duplicate_cleanup._flatten_existing_company_merges(self.test_staff)

        source.refresh_from_db()
        middle.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(source.merged_into_id, terminal.id)
        self.assertEqual(middle.merged_into_id, terminal.id)
        self.assertEqual(job.company_id, terminal.id)
        self.assertFalse(
            Company.objects.filter(merged_into__merged_into__isnull=False).exists()
        )

    def test_applies_named_company_then_person_decisions(self) -> None:
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
        CompanyPersonLink.objects.create(
            company=destination_company,
            person=destination_person,
        )
        CompanyPersonLink.objects.create(
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

        company_decision = CompanyMergeDecision(
            canonical_name="Northland Roofs NZ",
            names=("CASH SALE - Northland Roofs NZ", "Northland Roofs NZ"),
            expected_rows=2,
            evidence="same production email, phone and Ace Punia",
        )
        person_decision = PersonMergeDecision(
            canonical=PersonSelector(
                "ACE PUNIA", "ace@example.com", "Northland Roofs NZ"
            ),
            members=(
                PersonSelector("ACE PUNIA", "ace@example.com", "Northland Roofs NZ"),
                PersonSelector(
                    "Ace Punia",
                    "ACE@example.com",
                    "CASH SALE - Northland Roofs NZ",
                ),
            ),
            expected_people=2,
            evidence="same production email and phone",
        )

        with (
            patch.object(
                kan278_duplicate_cleanup,
                "REVIEWED_COMPANY_MERGES",
                (company_decision,),
            ),
            patch.object(
                kan278_duplicate_cleanup,
                "REVIEWED_PERSON_MERGES",
                (person_decision,),
            ),
            patch.object(kan278_duplicate_cleanup, "INVALID_LINKS", ()),
            patch.object(kan278_duplicate_cleanup, "_repair_matt_green"),
            patch.object(
                kan278_duplicate_cleanup,
                "_assert_residuals_are_defended",
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
        self.assertEqual(job.person_id, destination_person.id)
        self.assertFalse(Person.objects.filter(id=source_person.id).exists())

    def test_flattens_chain_created_by_reviewed_company_decisions(self) -> None:
        terminal = Company.objects.create(
            name="Terminal Company",
            xero_last_modified=timezone.now(),
        )
        middle = Company.objects.create(
            name="Middle Company",
            xero_last_modified=timezone.now(),
        )
        source = Company.objects.create(
            name="Source Company",
            xero_last_modified=timezone.now(),
            merged_into=middle,
        )
        decisions = (
            CompanyMergeDecision(
                canonical_name="Terminal Company",
                names=("Middle Company", "Terminal Company"),
                expected_rows=2,
                evidence="fixture reviewed merge",
            ),
        )

        with (
            patch.object(
                kan278_duplicate_cleanup,
                "REVIEWED_COMPANY_MERGES",
                decisions,
            ),
            patch.object(
                kan278_duplicate_cleanup,
                "REVIEWED_PERSON_MERGES",
                (),
            ),
            patch.object(kan278_duplicate_cleanup, "INVALID_LINKS", ()),
            patch.object(kan278_duplicate_cleanup, "_repair_matt_green"),
            patch.object(
                kan278_duplicate_cleanup,
                "_assert_residuals_are_defended",
            ),
        ):
            company_count, person_count = apply_reviewed_duplicate_cleanup()

        source.refresh_from_db()
        middle.refresh_from_db()
        self.assertEqual(company_count, 1)
        self.assertEqual(person_count, 0)
        self.assertEqual(source.merged_into_id, terminal.id)
        self.assertEqual(middle.merged_into_id, terminal.id)
        self.assertFalse(
            Company.objects.filter(merged_into__merged_into__isnull=False).exists()
        )

    def test_changed_named_evidence_aborts_before_writes(self) -> None:
        destination = Company.objects.create(
            name="Destination",
            xero_last_modified=timezone.now(),
        )
        decision = CompanyMergeDecision(
            canonical_name="Destination",
            names=("Missing source", "Destination"),
            expected_rows=2,
            evidence="fixture evidence",
        )

        with (
            patch.object(
                kan278_duplicate_cleanup,
                "REVIEWED_COMPANY_MERGES",
                (decision,),
            ),
            patch.object(kan278_duplicate_cleanup, "REVIEWED_PERSON_MERGES", ()),
            patch.object(kan278_duplicate_cleanup, "INVALID_LINKS", ()),
        ):
            with self.assertRaisesRegex(RuntimeError, "Company evidence changed"):
                apply_reviewed_duplicate_cleanup()

        destination.refresh_from_db()
        self.assertIsNone(destination.merged_into_id)

    def test_cleanup_manifest_contains_no_uuid_literals(self) -> None:
        source = Path(kan278_duplicate_cleanup.__file__).read_text()
        uuid_literal = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        )
        self.assertIsNone(uuid_literal.search(source))
