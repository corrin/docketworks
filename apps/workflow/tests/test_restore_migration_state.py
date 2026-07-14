import importlib.util
import types
from pathlib import Path
from typing import ClassVar

from django.test import TestCase

REPO_ROOT = Path(__file__).resolve().parents[3]
POST_CHECK = REPO_ROOT / "scripts" / "restore_checks" / "check_post_migration_state.py"


def load_post_check() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_post_migration_state", POST_CHECK
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_post_migration_state.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RestoreMigrationStateTests(TestCase):
    check: ClassVar[types.ModuleType]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.check = load_post_check()

    def counts(self) -> dict[str, int]:
        return {
            "companies": 10,
            "contacts": 8,
            "contact_methods": 7,
            "jobs": 20,
            "calls": 5,
            "jobs_with_contact": 12,
            "calls_with_contact": 4,
        }

    def test_count_comparison_accepts_preservation_and_cleanup(self) -> None:
        before = self.counts()
        after = {**before, "contacts": 6, "contact_methods": 5}

        self.assertEqual(self.check.comparison_errors(before, after), [])

    def test_count_comparison_reports_lost_business_references(self) -> None:
        before = self.counts()
        after = {**before, "jobs_with_contact": 11}

        self.assertEqual(
            self.check.comparison_errors(before, after),
            ["jobs_with_contact: before=12, after=11"],
        )

    def test_current_test_schema_satisfies_structural_invariants(self) -> None:
        self.assertEqual(self.check.structural_errors(), [])
