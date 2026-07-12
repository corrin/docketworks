import csv
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.company.models import Person
from apps.testing import BaseTestCase


class CleanupDuplicatePeopleCommandTests(BaseTestCase):
    """The cleanup CSV is a reviewed, stale-safe boundary around destructive merges."""

    def _path(self) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        handle.close()
        return Path(handle.name)

    def test_preview_prefills_only_isolated_high_confidence_pair(self) -> None:
        Person.objects.create(name="Jane Smith", email="jane@example.com")
        Person.objects.create(name="jane smith", email="JANE@example.com")
        Person.objects.create(name="Accounts")
        Person.objects.create(name=" accounts ")
        path = self._path()

        call_command("cleanup_duplicate_people", preview=str(path))

        with path.open(newline="", encoding="utf-8") as input_file:
            rows = list(csv.DictReader(input_file))
        self.assertEqual(len(rows), 2)
        actions_by_confidence = {row["confidence"]: row["action"] for row in rows}
        self.assertEqual(actions_by_confidence["high"], "merge")
        self.assertEqual(actions_by_confidence["low"], "")

    def test_apply_merges_selected_rows(self) -> None:
        first = Person.objects.create(name="Jane Smith", email="jane@example.com")
        second = Person.objects.create(name="jane smith", email="JANE@example.com")
        path = self._path()
        call_command("cleanup_duplicate_people", preview=str(path))

        call_command("cleanup_duplicate_people", apply=str(path))

        self.assertEqual(Person.objects.filter(id__in=[first.id, second.id]).count(), 1)

    def test_apply_rejects_stale_person(self) -> None:
        Person.objects.create(name="Jane Smith", email="jane@example.com")
        second = Person.objects.create(name="jane smith", email="JANE@example.com")
        path = self._path()
        call_command("cleanup_duplicate_people", preview=str(path))
        second.name = "Jane Smith Updated"
        second.save(update_fields=["name", "updated_at"])

        with self.assertRaisesRegex(CommandError, "changed after preview"):
            call_command("cleanup_duplicate_people", apply=str(path))
