import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.utils import timezone

from apps.company.models import Company
from apps.testing import BaseTestCase


class CleanupDuplicateIdentitiesCommandTests(BaseTestCase):
    def test_preview_and_apply_grouped_company_merge(self) -> None:
        first = Company.objects.create(
            name="Acme Ltd", xero_last_modified=timezone.now()
        )
        second = Company.objects.create(
            name="CASH SALE - Acme Limited", xero_last_modified=timezone.now()
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicates.csv"
            call_command("cleanup_duplicate_identities", preview=str(path))

            with path.open(newline="", encoding="utf-8") as input_file:
                rows = list(csv.DictReader(input_file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["entity_kind"], "company")
            self.assertEqual(rows[0]["action"], "merge")

            call_command("cleanup_duplicate_identities", apply=str(path))

        first.refresh_from_db()
        second.refresh_from_db()
        merged = [company for company in (first, second) if company.merged_into_id]
        self.assertEqual(len(merged), 1)
